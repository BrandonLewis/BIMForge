"""road-corridor V1.2 part C: the family builds a shared-use path beside
the road (P.6)."""
import contextlib
import copy
import io
import math
import re
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
    # a tread: the buffer, the tread and its clear strip in place of the
    # outer shoulder
    pp = copy.deepcopy(PARAMS)
    pp["path"]["equestrian"] = {"courses": [{"name": "EQ-DG", "type": "PAVEMENT",
                                             "thickness": 0.33}]}
    c = parse(pp, al.s_start, al.s_end, alignment=al, profile=prof)
    assert ground_reach(c) == pytest.approx(17.0 + 10.0 + 12.0 + 2.0 + 6.0 + 8.0
                                            + 3.0 + 150.0)


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


def test_the_family_writes_the_path_tables(built):
    m, _log = built
    assert m.tables["path"].splitlines()[0].startswith("station,side,separation_ft")
    lines = m.tables["path"].splitlines()[1:]
    first = lines[0].split(",")
    assert (first[0], first[1], first[2]) == ("1000.00", "R", "10.00")
    assert any(line.split(",")[-1] == "deck" for line in lines)      # on the bridge
    assert any("approach" in line.split(",")[-1] for line in lines)
    checks = m.tables["path_checks"].splitlines()
    assert checks[0] == "check,from,to,value,limit,reference"
    assert any(line.startswith("separation<5ft on an approach,") for line in checks)


@pytest.mark.parametrize("side", ["L", "R"])
def test_the_path_on_the_curve_passes_the_gate(tmp_path, side):
    # the path's 1 ft end transitions on the road's 7 %: the earthwork's
    # section points lean as far along the line as the bay is long
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.tests.test_road_corridor import PAYCODES
    params = copy.deepcopy(CURVE)
    params["path"]["side"] = side
    (tmp_path / "rc.paycodes.yaml").write_text(PAYCODES, "utf-8")
    spec = {"family": "road-corridor", "params": params,
            "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": "out/rc.ifc"},
            "project": {"name": "Path fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": "IFC4X3_ADD2", "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre gate and the post gate both passed
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]


def test_a_short_path_gap_splits_the_strip_wall_and_its_rail():
    # 20 ft, under the 25 ft interval that merges same-kind walls: the strip
    # wall still stops either side of the path gap (no path walls inside it)
    p = wall_params(UP)
    p["path"]["gaps"] = [{"from": 1300, "to": 1320, "kind": "structure"}]
    m = build(p)
    rails = sorted(e.name for e in path_rails(m))
    assert len(rails) == 2
    rows = [r.split(",") for r in m.tables["walls"].splitlines()[1:]]
    path_rows = [r for r in rows if "path" in r[1]]
    assert len(path_rows) == 2
    assert all(float(r[3]) <= 1299.5 or float(r[2]) >= 1320.5 for r in path_rows)


def test_a_too_tall_strip_wall_is_a_candidate_carrying_the_path():
    m = build(wall_params(DIP, max_wall_height_ft=5))
    lines = m.tables["structures"].splitlines()
    assert lines[0].endswith(",carries,location")
    assert [line.split(",")[0] for line in lines[1:]] == ["R"]
    # beside the road, at the strip's wall: its location as the walls table's
    assert lines[1].endswith(",path,strip")
    walls = [w.split(",") for w in m.tables["walls"].splitlines()[1:]]
    assert any(w[:2] == ["R", "wall-road"] and w[-1] == "strip" for w in walls)


TREAD = {"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0.33}],
         "fence": True}


def tread_params(**over):
    p = copy.deepcopy(PARAMS)
    p["path"] = dict(copy.deepcopy(PATH), equestrian=copy.deepcopy(TREAD), **over)
    return p


@pytest.fixture(scope="module")
def tread_built():
    return build(tread_params())


def test_the_tread_has_its_own_part_and_courses(tread_built):
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.gate import check_stated_quantities
    m = tread_built
    treads = [e for e in m.elements if e.name.startswith("EQ-DG tread STA ")]
    assert sorted(e.name for e in treads) == sorted(
        f"EQ-DG tread STA {b}" for b in (
            "10+00.00 to 11+00.00", "11+00.00 to 12+00.00", "12+00.00 to 13+00.00",
            "13+50.00 to 14+00.00", "14+00.00 to 15+00.00", "15+00.00 to 16+00.00"))
    for el in treads:
        assert (el.ifc_class, el.predefined_type, el.family_class) == (
            "IfcCourse", "PAVEMENT", dims.COURSE)
        assert el.spatial_part.predefined_type == "EQUESTRIANTRAIL"
        assert el.spatial_part.family_class == dims.EQUESTRIAN_TREAD
        assert el.spatial_part.parent.predefined_type == "ROADSEGMENT"
        assert el.dimensions["Width"] == pytest.approx(8.0)
        assert el.dimensions["Thickness"] == pytest.approx(0.33)
    # on a tangent band its box: 8 ft by 0.33 ft along the 1 % grade
    el = m.element("EQ-DG tread STA 10+00.00 to 11+00.00")
    assert el.quantities["volume_cf"] == pytest.approx(
        8.0 * 0.33 * 100.0 * (1.0 + 0.01 ** 2) ** 0.5, rel=1e-9)
    assert el.standard_qto["Qto_CourseBaseQuantities"]["Volume"][2] == dims.VOLUME
    # the tread's centre: 17 + 10 + 12 + 6 + 4 ft right
    assert el.dimensions["Offset"] == pytest.approx(-49.0, abs=0.01)
    # the paved path's courses keep their own part
    paved = m.element("PATH-HMA path STA 10+00.00 to 11+00.00")
    assert paved.spatial_part.predefined_type == "SHAREDUSEPATH"
    assert check_stated_quantities(m) == []


def test_the_fence_runs_over_the_tread_and_stops_at_the_gap(tread_built):
    from bimforge.author.corridor import dimensions as dims
    m = tread_built
    fences = sorted(e.name for e in m.elements if e.name.startswith("Path fence "))
    # one each side of the bridge: it stops at the gap
    assert fences == ["Path fence R STA 10+00.00 to 13+00.00",
                      "Path fence R STA 13+50.00 to 16+00.00"]
    fence = m.element(fences[0])
    assert (fence.ifc_class, fence.predefined_type, fence.type_name,
            fence.family_class) == ("IfcRailing", "FENCE", "Path fence", dims.PATH_FENCE)
    assert fence.spatial_part.predefined_type == "EQUESTRIANTRAIL"
    assert fence.dimensions["RailHeight"] == pytest.approx(4.5)
    assert fence.psets["BIMForge_Guardrail"]["RailHeight"] == ("length", pytest.approx(4.5))
    assert fence.standard_qto["Qto_RailingBaseQuantities"]["Length"] == (
        "length", pytest.approx(300.0), dims.LENGTH)
    # on the buffer, 3 ft in from the tread: 17 + 10 + 12 + 3 ft right
    (lf,) = fence.geometry
    assert lf.rings[0][0][0] == pytest.approx(-42.0, abs=0.01)
    # a 0.25 ft band toward the tread (u falls to the right), up 4.5 ft of
    # elevation: v is along the plane, 1 / cos of the road's 1 % grade more
    # (the loft keeps its rings in its own winding)
    us = sorted({round(u, 9) for u, _v in lf.rings[0]})
    vs = sorted({round(v, 9) for _u, v in lf.rings[0]})
    assert us == [pytest.approx(-42.25, abs=0.01), pytest.approx(-42.0, abs=0.01)]
    assert us[1] - us[0] == pytest.approx(0.25)
    assert len(vs) == 2
    assert vs[1] - vs[0] == pytest.approx(4.5 * (1.0 + 0.01 ** 2) ** 0.5, rel=1e-8)
    assert (lf.s0, lf.s1) == (pytest.approx(1000.0), pytest.approx(1300.0))
    # it stops at a path gap too, where the path's 1 ft transitions end
    gapped = build(tread_params(gaps=[{"from": 1450, "to": 1480, "kind": "structure"}]))
    assert sorted(e.name for e in gapped.elements if e.name.startswith("Path fence ")) == [
        "Path fence R STA 10+00.00 to 13+00.00", "Path fence R STA 13+50.00 to 14+49.00",
        "Path fence R STA 14+81.00 to 16+00.00"]
    # no fence without `fence: true`
    p = tread_params()
    p["path"]["equestrian"]["fence"] = False
    assert not [e for e in build(p).elements if e.name.startswith("Path fence ")]


def test_the_deck_lists_the_width_it_must_carry(tread_built):
    deck = [line for line in tread_built.tables["path_checks"].splitlines()
            if line.startswith("deck width")]
    # 1.5 (deck separation) + 12 + 6 + 8 + 3
    assert deck == ["deck width to carry (tread rail 4.50 ft),1300.00,1350.00,30.50,,"
                    "USFS-EDG Ch. 5; CSP-TH 18.2.1"]


def tread_wall_params():
    """Task 10's UP corridor with a tread and a right footprint of 70 ft:
    at the path's highest (7.5 ft above the road) the clear strip's end is
    56 ft out and about 13.7 ft above the ground, so its 2:1 fill would
    daylight about 83 ft out, past 70; near the ends it fits."""
    p = wall_params(UP)
    p["path"]["equestrian"] = copy.deepcopy(TREAD)
    p["section"] = dict(copy.deepcopy(SECTION), side_slopes=dict(
        SECTION["side_slopes"], footprint_ft={"R": 70.0}))
    return p


def test_a_wall_along_the_tread_carries_the_54_in_rail():
    from bimforge.author.corridor import dimensions as dims
    m = build(tread_wall_params())
    by_type = {}
    for e in m.elements:
        if e.ifc_class == "IfcRailing" and e.predefined_type == "GUARDRAIL":
            by_type.setdefault(e.type_name, []).append(e)
    assert set(by_type) == {"Path rail", "Equestrian rail"}   # strip and outer walls
    (eq,) = by_type["Equestrian rail"]
    assert eq.name.startswith("Equestrian rail R STA ")
    assert (eq.family_class, eq.dimensions["RailHeight"]) == (
        dims.EQUESTRIAN_RAIL, pytest.approx(4.5))
    assert eq.psets["BIMForge_Guardrail"]["RailHeight"] == ("length", pytest.approx(4.5))
    assert eq.spatial_part.predefined_type == "EQUESTRIANTRAIL"
    # at o, the clear strip's end: 17 + 10 + 12 + 6 + 8 + 3 ft right
    assert eq.geometry[0].rings[0][0][0] == pytest.approx(-56.0, abs=0.01)
    for e in by_type["Path rail"]:                # the strip wall keeps 42 in
        assert (e.family_class, e.dimensions["RailHeight"]) == (
            dims.PATH_RAIL, pytest.approx(3.5))
        assert e.spatial_part.predefined_type == "SHAREDUSEPATH"


@pytest.mark.parametrize("schema", ["IFC4X3_ADD2", "IFC4"])
def test_the_tread_passes_the_schema(tmp_path, schema):
    import ifcopenshell
    import ifcopenshell.util.element as E
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import schema_issues
    (tmp_path / "rc.paycodes.yaml").write_text(
        "rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
        "groups:\n  rc_pave: {measure: GrossVolume}\n"
        "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
        "            item_number: \"0001\", description: \"Pavement\"}\n", "utf-8")
    # the bridge's corridor, its fence split at the road gap; and a wall
    # along the tread and one in the strip, so both rails are written
    walled = tread_wall_params()
    walled["path"]["equestrian"]["fence"] = True
    files = {}
    for which, params in (("gap", tread_params()), ("walls", walled)):
        spec = {"family": "road-corridor", "params": params,
                "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": f"out/{which}.ifc"},
                "project": {"name": "Tread fixture", "epsg": 2226,
                            "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=11)),
                            "schema": schema}}
        if schema == "IFC4X3_ADD2":
            spec["project"]["facility"] = {"kind": "road"}
        path = tmp_path / f"{which}.spec.yaml"
        path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
        f = files[which] = ifcopenshell.open(str(tmp_path / "out" / f"{which}.ifc"))
        assert not schema_issues(f), which
        # IFC4 has no IfcCourse: its courses are written as the class it
        # falls back to
        assert any((c.Name or "").startswith("EQ-DG tread STA ")
                   for c in f.by_type("IfcProduct")), which
    fences = sorted(r.Name for r in files["gap"].by_type("IfcRailing")
                    if r.Name.startswith("Path fence "))
    assert fences == ["Path fence R STA 10+00.00 to 13+00.00",
                      "Path fence R STA 13+50.00 to 16+00.00"]
    railings = {r.Name.split(" R STA ")[0]: r for r in files["walls"].by_type("IfcRailing")}
    assert {"Path fence", "Equestrian rail", "Path rail"} <= set(railings)
    # IFC4's IfcRailingTypeEnum has no FENCE: it is written USERDEFINED
    # with FENCE as its ObjectType, which get_predefined_type reads
    for name, pdt in (("Path fence", "FENCE"), ("Equestrian rail", "GUARDRAIL"),
                      ("Path rail", "GUARDRAIL")):
        assert E.get_predefined_type(railings[name]) == pdt, name
        assert E.get_type(railings[name]).Name == name, name
    if schema == "IFC4X3_ADD2":
        parts = [p for p in files["gap"].by_type("IfcRoadPart")
                 if p.ObjectType == "EQUESTRIANTRAIL"]
        assert parts and all(p.PredefinedType == "USERDEFINED" for p in parts)
        for part in parts:
            refs = [r.RelatingClassification for r in part.HasAssociations
                    if r.is_a("IfcRelAssociatesClassification")]
            assert [r.Identification for r in refs] == ["road-corridor-equestrian-tread"]


def test_the_tread_on_the_curve_holds_its_formulas_and_volumes():
    # on the left, inside the curve: the tread's own grade along its length
    # (the profile's over 1 - kappa u, 20 ft farther out than the paved
    # centre) sets its theta, and at the PC and PT its rings are read on
    # the stretch's own side, as the paved courses' are
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.gate import check_stated_quantities
    params = copy.deepcopy(CURVE)
    params["path"]["equestrian"] = copy.deepcopy(TREAD)
    log = []
    m = build(params, log)
    treads = [e for e in m.elements if e.name.startswith("EQ-DG tread STA ")]
    assert {e.name for e in treads} >= {"EQ-DG tread STA 11+00.00 to 11+25.00",
                                        "EQ-DG tread STA 11+25.00 to 11+50.00",
                                        "EQ-DG tread STA 12+00.00 to 12+25.00",
                                        "EQ-DG tread STA 12+25.00 to 12+50.00"}
    for el in treads:
        # constant: a PC's or PT's ring read across the step would not be
        assert el.dimensions.get("Width") == pytest.approx(8.0), el.name
        volume = el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]
        assert volume[2:] == (dims.VOLUME,), el.name
        assert el.name not in log[0]
        box = el.dimensions["PathLength"] * 8.0 * 0.33
        assert abs(box - el.quantities["volume_cf"]) <= 1e-6 * el.quantities["volume_cf"]
    assert check_stated_quantities(m) == []


#: own stretches (phase 3): Task 9's corridor with no bridge, the path 20 ft
#: out, and the bump of test_corridor_own from 11+00 to 15+10.424; the
#: ground rises with the road (1 %) as it falls 2 % to the east, so both
#: hand-overs leave natural ground between road and path
from bimforge.author.tests.test_corridor_own import (BUMP, REJOIN, beside_tail,  # noqa: E402
                                                     vc)

OWN_FT = sum(x["length"] for x in BUMP)
#: the bump's PC to its first reverse-curve join, the second join to its
#: PT: own stations where its curvature steps
OWN_STEPS = ("1+04.72", "3+14.16")


def carry_on(path, z0, z1, g0, g1, to, lead=20.0):
    """The path's profile carries on the stretch's grade across both ends
    (g0 % at 11+00, g1 % at the rejoin): the road's 1 % but for a `lead` ft
    curve into g0 and out of g1, and the middle, which the stretch replaces,
    fitted to the elevations."""
    z = z0 - lead * (1.0 + g0) / 200.0 - 0.01 * (100.0 - lead)
    head, z = vc(1000.0, z, 1.0, 1.0, 100.0 - lead)
    into, _z = vc(1100.0 - lead, z, 1.0, g0, lead)
    mid = beside_tail(1100.0, z0, g0, z1, g1, to, end=to + 1.0)[:-1]
    out, z = vc(to, z1, g1, 1.0, lead)
    rest, _z = vc(to + lead, z, 1.0, 1.0, 1000.0)
    path["profile"] = {"curves": [head, into] + mid + [out, rest]}


def own_params(side="R", to=REJOIN, crest=None, swing=False, tread=False, **over):
    """The bump on `side` (turning away from the road first, or toward it
    with `swing`), its profile one grade (two PVIs) from the path's at 11+00
    to the path's at the rejoin, or with `crest` one vertical curve from
    +`crest` %; the path's profile carries on its grade across both ends."""
    p = copy.deepcopy(PARAMS)
    p.update(gaps=[], **over)
    p["ground"] = dict(p["ground"], slope_n=0.01)
    flip = (side == "L") != swing
    run = [dict(x, turn=("L" if x["turn"] == "R" else "R") if flip else x["turn"])
           for x in BUMP]
    z0, z1 = 299.48002 + 0.01 * 100.0, 299.48002 + 0.01 * (to - 1000.0)
    g = 100.0 * (z1 - z0) / OWN_FT
    g_in, g_out = (g, g) if crest is None else (crest, 2.0 * g - crest)
    p["path"] = dict(copy.deepcopy(PATH), side=side, separation=[[1000, 20.0]], own=[{
        "from": 1100, "to": to, "run": run,
        "profile": {"curves": [{"bvc_station": 0.0, "bvc_elev": z0, "g_in_pct": g_in,
                                "g_out_pct": g_out, "length_ft": OWN_FT,
                                "evc_station": OWN_FT, "evc_elev": z1}]}}])
    carry_on(p["path"], z0, z1, g_in, g_out, to)
    if tread:
        p["path"]["equestrian"] = copy.deepcopy(TREAD)
    return p


def own_courses(m, where="path"):
    return [e for e in m.elements if e.ifc_class == "IfcCourse"
            and f" {where} 1 STA " in e.name]


def own_earthwork(m):
    return [e for e in m.elements if e.name.startswith(("Cut path 1 ", "Fill path 1 "))]


@pytest.fixture(scope="module")
def own_built():
    log = []
    return build(own_params(), log), log[0]


def test_the_path_table_marks_the_hand_over_and_the_rejoin(own_built):
    # outputs.path is on road stations: it jumps from the hand-over to the
    # rejoin, and their rows say why
    m, _log = own_built
    rows = [r.split(",") for r in m.tables["path"].splitlines()[1:]]
    at = [float(r[0]) for r in rows]
    assert len(at) == len(set(at)) and not [x for x in at if 1100.0 < x < REJOIN - 0.01]
    marked = [(r[0], r[8], r[10]) for r in rows if "own 1" in r[10]]
    assert marked == [("1100.00", "ground", "own 1 hand-over"),
                      (f"{REJOIN:.2f}", "ground", "own 1 rejoin")]


def test_an_own_stretch_builds_its_own_path_and_earthwork(own_built):
    m, _log = own_built
    assert {e.name for e in own_courses(m)} >= {"PATH-HMA path 1 STA 0+00.00 to 1+00.00",
                                                 "PATH-AB path 1 STA 4+00.00 to 4+18.88"}
    for el in own_courses(m):
        (lf,) = el.geometry
        assert lf.alignment.name == "ML path 1"
        # the path's own part, in the run it hands over from
        assert el.spatial_part.predefined_type == "SHAREDUSEPATH"
        assert el.spatial_part.parent.name == "Segment 1"
        # its paved width centred on its own alignment: the box, on its grade
        assert el.dimensions["Width"] == pytest.approx(12.0)
        assert el.standard_qto["Qto_CourseBaseQuantities"]["Volume"][2] == (
            "PathLength * Width * Thickness"), el.name
    earth = own_earthwork(m)
    assert {e.ifc_class for e in earth} == {"IfcEarthworksFill"}
    for el in earth:
        assert el.spatial_part.name == "Segment 1"
    # beside the road the path stops at the hand-over and starts at the rejoin
    for el in path_courses(m):
        (lf,) = el.geometry
        assert lf.s1 <= 1100.0 + 1e-6 or lf.s0 >= REJOIN - 1e-6, el.name
    # the road's mass haul is the road's bands only, and its earthwork
    # alone carries it
    assert all(row.station <= 1600.0 for row in m.mass_haul)
    assert not any("BIMForge_MassHaul" in e.psets for e in earth)


def test_an_own_stretch_s_courses_split_at_its_curvature_steps(own_built):
    m, _log = own_built
    assert sorted({e.name.split(" STA ")[1] for e in own_courses(m)}) == [
        "0+00.00 to 1+00.00", "1+00.00 to 1+04.72", "1+04.72 to 2+00.00",
        "2+00.00 to 3+00.00", "3+00.00 to 3+14.16", "3+14.16 to 4+00.00",
        "4+00.00 to 4+18.88"]


def test_an_own_stretch_s_earthwork_is_closed_and_meets_its_volumes(own_built):
    from collections import Counter

    from bimforge.author.gate import check_stated_quantities
    m, _log = own_built
    assert check_stated_quantities(m) == []
    assert own_earthwork(m)
    for el in own_earthwork(m):
        for g in el.geometry:
            (d,) = g.body_solids()
            directed = Counter((a, b) for t in d["tris"] for a, b in zip(t, t[1:] + t[:1]))
            assert all(n == 1 and directed[b, a] == 1
                       for (a, b), n in directed.items()), el.name


def _build_ifc(tmp_path, params, log=None):
    """`params` built through build_from_spec, the pre and post gates
    passed (every Formula recomputed), to an IFC4X3 file, opened; with
    walls: auto its walls table too (out/rc.walls.csv)."""
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    (tmp_path / "rc.paycodes.yaml").write_text(
        "rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
        "groups:\n  rc_pave: {measure: GrossVolume}\n"
        "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
        "            item_number: \"0001\", description: \"Pavement\"}\n", "utf-8")
    outputs = {"ifc": "out/rc.ifc"}
    if params.get("walls") == "auto":
        outputs["walls"] = "out/rc.walls.csv"
    spec = {"family": "road-corridor", "params": params,
            "paycodes": "./rc.paycodes.yaml", "outputs": outputs,
            "project": {"name": "Own fixture", "epsg": 2226, "base": [E0, N0, 300.0],
                        "guid_ns": str(uuid.UUID(int=11)), "schema": "IFC4X3_ADD2",
                        "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    if log is not None:
        log.append(err.getvalue())
    return ifcopenshell.open(str(tmp_path / "out" / "rc.ifc"))


def _vertical(f, name):
    import ifcopenshell.api.alignment as alapi
    (al,) = [a for a in f.by_type("IfcAlignment") if a.Name == name]
    return al, [s.DesignParameters
                for s in alapi.get_layout_segments(alapi.get_vertical_layout(al))]


def test_the_own_alignment_is_an_ifcalignment_with_a_two_pvi_profile(tmp_path):
    import ifcopenshell.api.alignment as alapi

    from bimforge.author.gate import alignment_issues
    f = _build_ifc(tmp_path, own_params())
    assert not alignment_issues(f)
    own, segs = _vertical(f, "ML path 1")
    assert [s.PredefinedType for s in segs if s.HorizontalLength > 0] == [
        "CONSTANTGRADIENT"]
    hsegs = [s.DesignParameters
             for s in alapi.get_layout_segments(alapi.get_horizontal_layout(own))]
    assert [s.PredefinedType for s in hsegs if s.SegmentLength > 0] == [
        "CIRCULARARC"] * 3
    assert [r.RelatingObject.is_a() for r in own.Decomposes] == ["IfcProject"]


def test_a_run_that_swings_into_the_road_is_refused():
    with pytest.raises(ValueError, match=r"path\.own\[0\]: its footprint at path "
                                         r"station .* crosses the road's at "):
        build(own_params(swing=True))


def test_an_own_hand_over_without_ground_between_is_refused():
    # 10 ft out, the road's fill and the path's inner fill meet at 11+00
    p = own_params()
    p["path"]["separation"] = [[1000, 10.0]]
    with pytest.raises(ValueError, match=r"path\.own\[0\]: the hand-over at "
                                         r"11\+00\.00 does not leave natural ground"):
        build(p)


#: a footprint on the path's side that the own stretch's outer fill, past
#: the tread's clear strip 23 ft out, passes where the crest lifts it (and
#: the path's outer slope beside the road, 66 ft out, everywhere)
OWN_FOOTPRINT = {"L": 30.0, "R": 40.0}


@pytest.mark.parametrize("side", ["L", "R"])
def test_a_graded_curved_own_stretch_with_a_tread_passes_the_gate(tmp_path, side):
    import ifcopenshell.util.element as E

    from bimforge.author.alignment import sta
    from bimforge.author.gate import FORMULA_TOLERANCE, alignment_issues
    section = dict(copy.deepcopy(SECTION), side_slopes=dict(
        SECTION["side_slopes"], footprint_ft={side: OWN_FOOTPRINT[side]}))
    log = []
    f = _build_ifc(tmp_path, own_params(side=side, crest=6.0, tread=True,
                                        walls="auto", section=section), log)
    assert not alignment_issues(f)
    _own, segs = _vertical(f, "ML path 1")
    assert [s.PredefinedType for s in segs if s.HorizontalLength > 0] == [
        "PARABOLICARC"]
    # the tread's courses hold their formula at the PC, the PT and the
    # reverse-curve joins: each stretch's end rings read on its own side
    treads = {c.Name: c for c in f.by_type("IfcCourse")
              if (c.Name or "").startswith("EQ-DG tread 1 STA ")}
    for at in OWN_STEPS:
        assert f"EQ-DG tread 1 STA {at[0]}+00.00 to {at}" in treads, at
        assert any(n.startswith(f"EQ-DG tread 1 STA {at} to ") for n in treads), at
    assert not [line for line in log[0].splitlines()
                if " 1 STA " in line and "withheld" in line]
    for name, c in treads.items():
        qto = E.get_psets(c)["Qto_CourseBaseQuantities"]
        dims = E.get_psets(c)["BIMForge_Dimensions"]
        box = dims["PathLength"] * dims["Width"] * dims["Thickness"]
        assert abs(box - qto["Volume"]) <= FORMULA_TOLERANCE * qto["Volume"], name
    # its walls in the walls table, on its own stations, and their rails
    rows = [w.split(",") for w in
            (tmp_path / "out" / "rc.walls.csv").read_text("utf-8").splitlines()]
    (row,) = [r for r in rows[1:] if r[-1] == "own 1"]
    # a fill wall at o, on the outer side, about 1+00 to 3+11 on the right
    # (0+54.50 to 3+61 on the left, the ground higher there)
    assert row[:2] == [side, "fill"] and float(row[4]) == pytest.approx(23.0)
    assert 0.0 < float(row[2]) < float(row[3]) < OWN_FT
    # along the tread: the Equestrian rail, in the tread's part
    rails = sorted(r.Name for r in f.by_type("IfcRailing") if " path 1 " in r.Name)
    assert rails == [f"Equestrian rail path 1 {side} STA {sta(float(row[2]))} to "
                     f"{sta(float(row[3]))}",
                     f"Path fence path 1 {side} STA 0+00.00 to 4+18.88"]
    for r in f.by_type("IfcRailing"):
        if " path 1 " in r.Name:
            (part,) = [x.RelatingStructure for x in r.ContainedInStructure]
            assert part.ObjectType == "EQUESTRIANTRAIL", r.Name
    # stationed on the line each lies along: the own stretch's on its own
    # alignment, the rest - the path beside the road before the hand-over
    # and after the rejoin too, along the own line's extension - on ML
    from bimforge.bim.linear_ref import read
    refs = read(f)
    on = {el.Name: refs[el.GlobalId]["Alignment"] for el in f.by_type("IfcElement")
          if el.GlobalId in refs}
    own = {n for n in on if re.search(r"\b(path|tread) 1\b", n)}
    assert len(own) > 20 and len(on) - len(own) > 20
    assert {n: a for n, a in on.items() if a != ("ML path 1" if n in own else "ML")} == {}


def test_the_ground_reaches_past_an_own_stretch():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import ground_reach
    p = own_params()
    al = Alignment(p["alignment"]["pob"], p["alignment"]["run"])
    c = parse(p, al.s_start, al.s_end, alignment=al,
              profile=Profile(p["profile"]["curves"]))
    # its centreline 17 + 20 + 6 ft out at the hand-over, then the bump's
    # 2 R (1 - cos 20 deg) farther; its paved half and shoulder, then the
    # 150 ft daylight limit (the road's own reach is 203 ft)
    wander = 43.0 + 2.0 * 300.0 * (1.0 - math.cos(math.radians(20.0)))
    assert ground_reach(c) == pytest.approx(wander + 6.0 + 2.0 + 150.0, abs=0.05)


def own_gap_params(gap, **over):
    p = own_params(**over)
    p["path"]["own"][0]["gaps"] = [{"from": gap[0], "to": gap[1], "kind": "structure"}]
    return p


def test_an_own_gap_splits_the_own_fence():
    m = build(own_gap_params((150, 180), tread=True))
    assert sorted(e.name for e in m.elements if e.name.startswith("Path fence path 1 ")) == [
        "Path fence path 1 R STA 0+00.00 to 1+50.00",
        "Path fence path 1 R STA 1+80.00 to 4+18.88"]


def test_a_swing_into_the_road_past_an_own_gap_is_refused():
    # the gap 0+10 to 0+30 ends the first own run: the crossing at 0+75 is
    # in the second, whose footprint is checked as the first's is
    with pytest.raises(ValueError, match=r"path\.own\[0\]: its footprint at path "
                                         r"station 0\+75\.00 crosses the road's at "):
        build(own_gap_params((10, 30), swing=True))


#: an own stretch in cut: on the left, the ground rising 10 % to the west,
#: rock 3 ft down at 10+00 to 9 ft at 16+00
def own_cut_params():
    p = own_params(side="L")
    p["ground"]["slope_e"] = -0.10
    p["section"] = copy.deepcopy(SECTION)
    p["section"]["side_slopes"]["cut"]["rock"] = {
        "depth_ft": [[1000, 3.0], [1600, 9.0]], "ratio": 0.5, "bench_ft": 6.0}
    return p


@pytest.fixture(scope="module")
def own_cut_built():
    return build(own_cut_params())


def test_an_own_cut_reads_its_rock_depth_from_the_hand_over_to_the_rejoin(
        own_cut_built):
    # the road's depth at 11+00 (4 ft) to its depth at 15+10.424 (8.10424
    # ft), linear on the own stations: each band's mean is its middle's
    cuts = sorted((e for e in own_earthwork(own_cut_built)
                   if e.ifc_class == "IfcEarthworksCut"),
                  key=lambda e: e.dimensions["StartStation"])
    assert len(cuts) == 5
    at = 3.0 + 6.0 * (REJOIN - 1000.0) / 600.0
    for el in cuts:
        mid = 0.5 * (el.dimensions["StartStation"] + el.dimensions["EndStation"])
        assert el.dimensions["RockDepth"] == pytest.approx(
            4.0 + (at - 4.0) * mid / OWN_FT, abs=1e-9), el.name


def test_an_own_cut_voids_the_terrain_and_is_closed(own_cut_built):
    from collections import Counter

    from bimforge.author.families.road_corridor import _terrain
    from bimforge.author.gate import check_stated_quantities
    m = own_cut_built
    cuts = [e for e in own_earthwork(m) if e.ifc_class == "IfcEarthworksCut"]
    assert cuts and all(e.name.startswith("Cut path 1 STA ") for e in cuts)
    assert {e.voids for e in cuts} == {_terrain(m)}
    assert check_stated_quantities(m) == []
    for el in cuts:
        assert el.quantities["volume_cf"] > 0.0
        for g in el.geometry:
            (d,) = g.body_solids()
            directed = Counter((a, b) for t in d["tris"] for a, b in zip(t, t[1:] + t[:1]))
            assert all(n == 1 and directed[b, a] == 1
                       for (a, b), n in directed.items()), el.name


def test_a_too_tall_own_wall_is_a_structure_candidate_on_own_stations():
    # the graded tread on the right, walls held to 5 ft: the own stretch's
    # outer fill wall (1+00 to 3+11, up to 9.93 ft) is a candidate carrying
    # the path at "own 1", as the walls table names it; along the own
    # centreline the ground rises (1 % north beats 2 % east while its
    # bearing stays within 20 deg of north), so its low point is its start
    section = dict(copy.deepcopy(SECTION), side_slopes=dict(
        SECTION["side_slopes"], footprint_ft={"R": OWN_FOOTPRINT["R"]}))
    m = build(own_params(side="R", crest=6.0, tread=True, walls="auto",
                         section=section, max_wall_height_ft=5))
    walls = [w.split(",") for w in m.tables["walls"].splitlines()[1:]]
    (wall,) = [w for w in walls if w[-1] == "own 1"]
    assert wall[-2] == "yes"                                   # too tall
    rows = [r.split(",") for r in m.tables["structures"].splitlines()[1:]]
    (own,) = [r for r in rows if r[-1] == "own 1"]
    assert own == ["R", wall[2], wall[3], wall[6], wall[2], "path", "own 1"]
    # the path's outer walls beside the road stand 3.95 ft: no candidate
    assert rows == [own]
