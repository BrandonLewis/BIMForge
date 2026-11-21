"""road-corridor: the family, built directly and through est-bim build (P.6)."""
import copy
import csv
import io
import uuid

import pytest

from bimforge.author.project import ProjectContext

N0, E0 = 1943000.0, 6594000.0
PARAMS = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0, "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 200.0},
                          {"kind": "curve", "delta": "11-27-33", "radius": 500.0,
                           "turn": "R", "length": 100.0},
                          {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 200.0}]},
    "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": 300.0, "g_in_pct": 1.0,
                            "g_out_pct": 1.0, "length_ft": 500.0,
                            "evc_station": 1500.0, "evc_elev": 305.0}]},
    "ground": {"source": "plane", "elevation": 300.0, "slope_e": 0.05},
    "section": {
        "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                       {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                        "slope": -0.05}],
        "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                    {"name": "AB", "type": "CORE", "thickness": 1.0}],
        "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                        "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}},
    "superelevation": [[1000, -0.02, -0.02], [1150, -0.02, -0.02],
                       [1200, 0.04, -0.04], [1300, 0.04, -0.04], [1350, -0.02, -0.02]],
    "gaps": [{"from": 1350, "to": 1400, "kind": "structure"},
             {"from": 1050, "to": 1100, "kind": "wall", "side": "L", "offset": 30.0}],
    "stations": {"interval": 25, "band": 100},
    "mass_haul": {"shrink": 0.1, "swell": 0.2},
}
CTX = ProjectContext(name="rc", epsg=2226, base_e=E0, base_n=N0, base_h=300.0,
                     guid_ns=uuid.UUID(int=9))


@pytest.fixture(scope="module")
def model():
    from bimforge.author.families.road_corridor import build
    return build(copy.deepcopy(PARAMS), CTX)


def courses(m):
    return [e for e in m.elements if e.ifc_class == "IfcCourse"]


def test_one_course_element_per_course_component_and_band(model):
    # bands: 10+00 to 11+00, 11+00 to 12+00, 12+00 to 13+00, 13+00 to 13+50, 14+00 to 15+00
    assert len(courses(model)) == 5 * 2 * 2
    assert {e.predefined_type for e in courses(model)} == {"PAVEMENT", "CORE"}
    assert {e.spatial_part.predefined_type for e in courses(model)} == {"CARRIAGEWAY", "SHOULDER"}
    assert {e.spatial_part.parent.predefined_type for e in courses(model)} == {"ROADSEGMENT"}


def test_nothing_is_built_inside_the_structure_gap(model):
    for el in courses(model):
        for lf in el.geometry:
            assert lf.s1 <= 1350.0 + 1e-6 or lf.s0 >= 1400.0 - 1e-6, el.name
    for el in model.elements:
        if "BIMForge_MassHaul" in el.psets:
            ps = el.psets["BIMForge_MassHaul"]
            assert ps["EndStation"] <= 1350.0 + 1e-6 or ps["StartStation"] >= 1400.0 - 1e-6


def test_the_structure_gap_ends_on_a_closed_face(model):
    # each course ends on its own ring at the gap station, capped; each
    # earthwork piece at the gap is a vertical column (its top over its base)
    ends = {1350.0: 0, 1400.0: 0}
    for el in courses(model):
        for lf in el.geometry:
            sections = lf.body_solids()[0]["exact"]["sections"]
            for s, sec in ((1350.0, sections[-1]), (1400.0, sections[0])):
                if sec["s"] == s:
                    assert sec["outer"] == lf.rings[0 if s == 1400.0 else -1]
                    ends[s] += 1
    # every course, component and side ends at the gap and starts past it
    assert ends == {1350.0: 2 * 2 * 2, 1400.0: 2 * 2 * 2}
    for el in model.elements:
        if el.ifc_class.startswith("IfcEarthworks"):
            for p in el.geometry:
                for b, t in zip(p.bottom, p.top):
                    assert b[:2] == pytest.approx(t[:2], abs=1e-9)


def test_every_course_meets_its_stated_volume(model):
    from bimforge.author.gate import check_stated_quantities
    labels = [q[0] for q in model.stated_quantities]
    assert len(labels) == len(courses(model))
    assert all("average end area" in s for s in labels)
    assert check_stated_quantities(model) == []


def test_the_stations_hold_every_geometry_point():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.families.road_corridor import geometry_stations
    al_p = PARAMS["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])
    # a vertical curve from 10+10 to 14+90, its PVI at 12+50
    prof = Profile([{"bvc_station": 1010.0, "bvc_elev": 300.0, "g_in_pct": 1.0,
                     "g_out_pct": -1.0, "length_ft": 480.0,
                     "evc_station": 1490.0, "evc_elev": 300.0}])
    assert geometry_stations(al, prof, 1000.0, 1350.0) == [1010.0, 1200.0, 1250.0, 1300.0]
    assert geometry_stations(al, prof, 1400.0, 1500.0) == [1490.0]


def test_the_subgrade_is_divided_by_the_ground_spacing():
    from bimforge.author.alignment import Alignment
    from bimforge.author.corridor.ground import PlaneGround
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import per_component
    al_p = PARAMS["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])
    p = copy.deepcopy(PARAMS)
    p["widths"] = [{"component": "shoulder", "side": "R",
                    "at": [[1200, 5.0], [1300, 10.0]]}]
    c = parse(p, al.s_start, al.s_end)
    assert per_component(c, PlaneGround(300.0)) == [1, 1]

    class Grid:
        spacing_ft = 3.0

    # the lane's 12 ft in 3 ft cells; the shoulder at its widest, 10 ft
    assert per_component(c, Grid()) == [4, 4]


def test_mass_haul_rows_follow_the_bands(model):
    rows = model.mass_haul
    assert [(r.start, r.station) for r in rows] == [
        (1000.0, 1100.0), (1100.0, 1200.0), (1200.0, 1300.0), (1300.0, 1350.0),
        (1400.0, 1500.0)]
    last = [e for e in model.elements if e.name.endswith("15+00.00")
            and "BIMForge_MassHaul" in e.psets]
    assert last
    assert last[0].psets["BIMForge_MassHaul"]["CumulativeCY"] == pytest.approx(
        rows[-1].cumulative_cy, abs=1e-3)


def test_each_element_carries_its_standard_set(model):
    sets = {e.ifc_class: set(e.standard_qto) for e in model.elements}
    assert sets["IfcCourse"] == {"Qto_CourseBaseQuantities"}
    assert sets.get("IfcEarthworksCut", {"Qto_EarthworksCutBaseQuantities"}) == {
        "Qto_EarthworksCutBaseQuantities"}
    assert sets.get("IfcEarthworksFill", {"Qto_EarthworksFillBaseQuantities"}) == {
        "Qto_EarthworksFillBaseQuantities"}
    assert "IfcEarthworksCut" in sets or "IfcEarthworksFill" in sets


def test_a_slope_that_finds_no_ground_is_refused():
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(PARAMS)
    p["ground"]["elevation"] = 0.0
    with pytest.raises(ValueError, match="finds no ground"):
        build(p, CTX)


PAYCODES = """\
rules:
  - {match: "(?i)^(HMA|AB) ", group: rc_pave}
  - {match: "(?i)^(Cut|Fill) ", group: rc_earth}
groups:
  rc_pave: {measure: GrossVolume}
  rc_earth: {measure: GrossVolume}
codes:
  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY, item_number: "0001",
            description: "Pavement courses"}
  RC-EARTH: {group: rc_earth, measure: GrossVolume, unit: CY, item_number: "0002",
             description: "Earthwork"}
"""


def _built(tmp_path, schema):
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    (tmp_path / "rc.paycodes.yaml").write_text(PAYCODES, "utf-8")
    spec = {"family": "road-corridor", "params": copy.deepcopy(PARAMS),
            "paycodes": "./rc.paycodes.yaml",
            "outputs": {"ifc": "out/rc.ifc", "masshaul": "out/rc.masshaul.csv"},
            "project": {"name": "Corridor fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": schema, "facility": {"kind": "road"}}}
    if schema == "IFC4":
        del spec["project"]["facility"]
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    # 0: the pre gate (the stated volumes) and the post gate both passed
    assert build_from_spec(str(path)) == 0
    return ifcopenshell.open(str(tmp_path / "out" / "rc.ifc")), tmp_path / "out"


@pytest.fixture(scope="module")
def x3(tmp_path_factory):
    return _built(tmp_path_factory.mktemp("x3"), "IFC4X3_ADD2")


def test_the_ifc4x3_file_is_a_road(x3):
    import ifcopenshell.util.element as E

    from bimforge.author.gate import alignment_issues, schema_issues
    f, out = x3
    assert not schema_issues(f) + alignment_issues(f)
    assert len(f.by_type("IfcRoad")) == 1
    parts = f.by_type("IfcRoadPart")
    assert sum(p.PredefinedType == "ROADSEGMENT" for p in parts) == 2
    assert {p.PredefinedType for p in parts} >= {"ROADSEGMENT", "CARRIAGEWAY", "SHOULDER"}
    for course in f.by_type("IfcCourse"):
        typ = E.get_type(course)
        assert typ is not None and typ.is_a("IfcCourseType")
        assert typ.PredefinedType in ("PAVEMENT", "CORE")
        assert "Qto_CourseBaseQuantities" in E.get_psets(course, qtos_only=True)
        items = course.Representation.Representations[0].Items
        assert all(i.is_a("IfcSectionedSolidHorizontal") for i in items)
    text = (out / "rc.masshaul.csv").read_text("utf-8")
    assert text.startswith("start,station,")


def test_the_tree_is_road_segment_lateral_part(x3):
    import ifcopenshell.util.element as E
    f, _out = x3

    def parent(x):
        return x.Decomposes[0].RelatingObject

    for part in f.by_type("IfcRoadPart"):
        if part.PredefinedType == "ROADSEGMENT":
            assert part.UsageType == "LONGITUDINAL"
            assert parent(part).is_a("IfcRoad")
        else:
            assert part.PredefinedType in ("CARRIAGEWAY", "SHOULDER")
            assert part.UsageType == "LATERAL"
            assert parent(part).PredefinedType == "ROADSEGMENT"
    for course in f.by_type("IfcCourse"):
        home = E.get_container(course)
        assert home.is_a("IfcRoadPart") and home.UsageType == "LATERAL"
    earth = [p for p in f.by_type("IfcProduct") if p.Name and p.Name.startswith(("Cut ", "Fill "))]
    assert earth
    for el in earth:
        assert E.get_container(el).PredefinedType == "ROADSEGMENT"


def test_the_earthwork_carries_its_standard_set_and_the_haul(x3):
    import ifcopenshell.util.element as E
    f, out = x3
    rows = {(float(r["start"]), float(r["station"])): float(r["cumulative_cy"])
            for r in csv.DictReader(io.StringIO((out / "rc.masshaul.csv").read_text("utf-8")))}
    assert len(rows) == 5
    seen = set()
    for el in f.by_type("IfcProduct"):
        if not (el.Name or "").startswith(("Cut ", "Fill ")):
            continue
        qtos = E.get_psets(el, qtos_only=True)
        want = ("Qto_EarthworksCutBaseQuantities" if el.Name.startswith("Cut ")
                else "Qto_EarthworksFillBaseQuantities")
        assert want in qtos
        ps = E.get_psets(el, psets_only=True)["BIMForge_MassHaul"]
        key = (ps["StartStation"], ps["EndStation"])
        assert ps["CumulativeCY"] == pytest.approx(rows[key], abs=1e-3)
        seen.add(key)
    assert seen == set(rows)


def test_the_ifc4_file_passes_the_schema(tmp_path):
    from bimforge.author.gate import schema_issues
    f, _out = _built(tmp_path, "IFC4")
    assert not schema_issues(f)
