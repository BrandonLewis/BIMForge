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
            assert ps["EndStation"][1] <= 1350.0 + 1e-6 or ps["StartStation"][1] >= 1400.0 - 1e-6


def test_the_structure_gap_ends_on_a_closed_face(model):
    # each course ends on its own ring at the gap station, capped (the
    # earthwork's closed skin is test_the_earthwork_is_merged_into_closed_bodies)
    ends = {1350.0: 0, 1400.0: 0}
    for el in courses(model):
        for lf in el.geometry:
            sections = lf.body_solids()[0]["exact"]["sections"]
            for s, sec in ((1350.0, sections[-1]), (1400.0, sections[0])):
                if sec["s"] == s:
                    assert sec["outer"] == lf.rings[0 if s == 1400.0 else -1]
                    ends[s] += 1
    # every course ends at the gap and starts past it: one lane body across
    # the crown, a shoulder body each side
    assert ends == {1350.0: 2 * 3, 1400.0: 2 * 3}


def _manifold(tris) -> bool:
    """Every edge of the indexed shell is used once each way: closed, and no
    edge shared by three or more faces."""
    from collections import Counter
    directed = Counter((a, b) for t in tris for a, b in zip(t, t[1:] + t[:1]))
    return all(n == 1 and directed[b, a] == 1 for (a, b), n in directed.items())


def test_the_innermost_course_is_one_body_across_the_crown(model):
    from bimforge.author.primitives import _signed_area2
    for el in courses(model):
        lofts = el.geometry
        if " lane " not in el.name:
            assert len(lofts) == 2, el.name          # a shoulder each side
            continue
        (lf,) = lofts
        assert {len(r) for r in lf.rings} == {6}
        wind = [_signed_area2(r) for r in lf.rings]
        assert all(w > 0.0 for w in wind) or all(w < 0.0 for w in wind)
        d = lf.body_solids()[0]
        assert _manifold(d["tris"]), el.name
    # 12 ft each side of the crown, 0.4 ft thick, 100 ft at 1% grade
    hma = model.element("HMA lane STA 10+00.00 to 11+00.00")
    assert hma.quantities["volume_cf"] == pytest.approx(
        0.4 * 24.0 * 100.0 * (1.0 + 0.01 ** 2) ** 0.5, rel=1e-9)


def test_the_earthwork_is_merged_into_closed_bodies(model):
    from bimforge.author.primitives import _signed_volume
    earth = [e for e in model.elements if e.ifc_class.startswith("IfcEarthworks")]
    assert earth
    for el in earth:
        got = 0.0
        for g in el.geometry:
            (d,) = g.body_solids()
            assert _manifold(d["tris"]), el.name
            v = d["verts"]
            got += _signed_volume([(v[a], v[b], v[c]) for a, b, c in d["tris"]])
        assert got == pytest.approx(el.quantities["volume_cf"], rel=1e-9)
        assert len(el.geometry) < 10, el.name        # regions, not columns


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
    ps = last[0].psets["BIMForge_MassHaul"]
    # stations as lengths, the ordinate as a volume, both converted to the
    # file's metres by emit_ifc; the texts in station form
    assert ps["StartStation"] == ("length", 1400.0)
    assert ps["EndStation"] == ("length", 1500.0)
    assert (ps["StartStationText"], ps["EndStationText"]) == ("14+00.00", "15+00.00")
    assert ps["CumulativeVolume"] == ("volume", pytest.approx(rows[-1].cumulative_cy * 27.0))


def test_each_element_carries_its_standard_set(model):
    sets = {e.ifc_class: set(e.standard_qto) for e in model.elements}
    assert sets["IfcCourse"] == {"Qto_CourseBaseQuantities"}
    assert sets.get("IfcEarthworksCut", {"Qto_EarthworksCutBaseQuantities"}) == {
        "Qto_EarthworksCutBaseQuantities"}
    assert sets.get("IfcEarthworksFill", {"Qto_EarthworksFillBaseQuantities"}) == {
        "Qto_EarthworksFillBaseQuantities"}
    assert "IfcEarthworksCut" in sets or "IfcEarthworksFill" in sets


#: a sag through a cut: the left side turns from cut (ditch and backslope)
#: to fill between 15+50 and 15+75, during the superelevation run-up
TURNING = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0, "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 600.0}]},
    "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": 298.0, "g_in_pct": 3.0,
                            "g_out_pct": 5.6, "length_ft": 1549.07,
                            "evc_station": 2549.07, "evc_elev": 364.61}]},
    "ground": {"source": "plane", "elevation": 300.0, "slope_n": 0.03, "slope_e": 0.04},
    "section": copy.deepcopy(PARAMS["section"]),
    "superelevation": [[1000.0, -0.02, -0.02], [1500.0, -0.02, -0.02],
                       [1600.0, 0.04, -0.04]],
    "stations": {"interval": 25, "band": 100},
}


def test_a_side_turning_from_cut_to_fill_gets_a_section_where_it_turns():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.frame import survey_point
    from bimforge.author.corridor.ground import PlaneGround
    from bimforge.author.corridor.params import parse
    from bimforge.author.corridor.section import kind_changes, resolve
    al_p = TURNING["alignment"]
    al, prof = Alignment(al_p["pob"], al_p["run"]), Profile(TURNING["profile"]["curves"])
    c = parse(TURNING, al.s_start, al.s_end)
    g = PlaneGround(300.0, n0=N0, e0=E0, slope_n=0.03, slope_e=0.04)

    def dz(s, u, v):
        n, e, z = survey_point(al, prof, s, u, v)
        return g.z(n, e) - z

    a, b = resolve(c, 1550.0, dz), resolve(c, 1575.0, dz)
    assert (a.sides["L"].kind, b.sides["L"].kind) == ("cut", "fill")
    (s,) = kind_changes(c, a, b, dz)
    assert 1550.0 < s < 1575.0
    turn = resolve(c, s, dz)
    # there the hinge is on the ground: the fill side is no more than a point
    assert turn.sides["L"].kind == "fill"
    assert abs(dz(s, *turn.subgrade["L"][-1])) < 1e-6
    assert turn.sides["L"].line[-1] == pytest.approx(turn.subgrade["L"][-1], abs=1e-6)
    assert kind_changes(c, b, resolve(c, 1600.0, dz), dz) == []


def test_the_band_where_a_side_turns_is_written_as_closed_bodies(tmp_path):
    # Fill 15+00 to 16+00 lofted the left side's ditch straight onto the
    # fill slope, a comb of slivers along the ground crossing; merged into
    # one ground-plane face, the engine drew it with 4 open edges
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.families.road_corridor import build
    from bimforge.bim.ifc_mesh import quiet_stdout
    from bimforge.author.model import StructureModel
    from bimforge.bim.ifc_mesh import solid_bodies
    m = build(copy.deepcopy(TURNING), CTX)
    one = StructureModel("one", CTX)
    for name in ("Fill STA 15+00.00 to 16+00.00", "Cut STA 15+00.00 to 16+00.00",
                 "Existing ground - design plane"):
        one.add(m.element(name))
    out = tmp_path / "turn.ifc"
    emit_ifc(one, str(out))
    with quiet_stdout():
        bodies = solid_bodies(str(out)).values()
    for info in bodies:
        if info["name"] == "Existing ground - design plane":
            continue                               # a surface (body="surface")
        t = info["topology"]
        assert (t["open_edges"], t["nonmanifold_edges"], t.get("nonmanifold_vertices", 0))             == (0, 0, 0), (info["name"], t)


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
    import contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert build_from_spec(str(path)) == 0
    (tmp_path / "out" / "build.log").write_text(err.getvalue(), "utf-8")
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


def test_the_road_is_positioned_on_its_alignment(x3):
    from bimforge.bim.linear_ref import REL_NAME
    f, _out = x3
    (rel,) = [r for r in f.by_type("IfcRelPositions") if r.Name == REL_NAME]
    assert rel.RelatingPositioningElement.Name == "ML"
    assert [p for p in rel.RelatedProducts if p.is_a("IfcRoad")] == list(f.by_type("IfcRoad"))
    assert any(p.is_a("IfcCourse") for p in rel.RelatedProducts)


def test_stationing_the_file_prints_nothing(x3, tmp_path, capfd):
    # ifcopenshell 0.9 dumps the topology of every sectioned solid it draws
    # to fd 1 (IfcOpenShell#9820); linear_ref draws them all to station them
    import shutil

    from bimforge.bim.linear_ref import annotate
    _f, out = x3
    copy_ = tmp_path / "rc.ifc"
    shutil.copy(out / "rc.ifc", copy_)
    capfd.readouterr()
    annotate(str(copy_))
    assert capfd.readouterr().out == ""


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
    fills = [p for p in f.by_type("IfcProduct") if (p.Name or "").startswith("Fill ")]
    assert fills
    for el in fills:
        assert E.get_container(el).PredefinedType == "ROADSEGMENT"
    # a cut is a feature of the ground it voids: it hangs off the TERRAIN
    # (IfcRelVoidsElement), not in the spatial tree
    for cut in f.by_type("IfcEarthworksCut"):
        assert not cut.ContainedInStructure
        (rel,) = cut.VoidsElements
        assert rel.RelatingBuildingElement.PredefinedType == "TERRAIN"


def _only_point_contacts(found: list) -> list:
    """The solid-body findings left once two earthwork regions meeting at a
    single point are set aside: where the ground crosses the design line
    exactly at a daylight point (depth 0 by construction), the fill on
    either side of a cut can meet there and nowhere else. That is the
    surfaces' own shape, not a crack; earthwork.merge keeps the two
    regions as separate bodies."""
    return [m for m in found
            if not (m.startswith(("Cut ", "Fill "))
                    and m.endswith("- 1 points where bodies touch"))]


def test_every_body_is_solid_but_the_engine_s_sectioned_caps(x3, model):
    # ifcopenshell 0.9 draws an IfcSectionedSolidHorizontal with its caps
    # doubled (IfcOpenShell#9820): 3n - 3 edges on an n-point ring, as it
    # does a SweptSection's (measured: 9 on a 4-point ring, 15 on the
    # 6-point lane ring, either way). A lane body is one 6-point ring; the
    # shoulders are two 4-point rings. Nothing else may be reported.
    from bimforge.author.gate import _ifc_solid_body_check
    from bimforge.bim.ifc_mesh import quiet_stdout
    _f, out = x3
    with quiet_stdout():
        found = _only_point_contacts(
            _ifc_solid_body_check(model, str(out / "rc.ifc")))
    assert found
    for msg in found:
        want = ("- 15 edges shared by 3+ faces" if " lane " in msg
                else "- 18 edges shared by 3+ faces")
        assert "(IfcCourse)" in msg and msg.endswith(want), msg


def test_on_ifc4x3_every_cut_voids_the_plane_s_terrain(x3, model):
    import ifcopenshell.util.element as E
    f, out = x3
    (terrain,) = [g for g in f.by_type("IfcGeographicElement")
                  if g.PredefinedType == "TERRAIN"]
    assert terrain.Name == "Existing ground - design plane"
    cuts = f.by_type("IfcEarthworksCut")
    assert {c.Name for c in cuts} == {e.name for e in model.elements
                                      if e.ifc_class == "IfcEarthworksCut"}
    assert not f.by_type("IfcEarthworksElement", include_subtypes=False)
    voids = {r.RelatedOpeningElement.Name: r.RelatingBuildingElement
             for r in f.by_type("IfcRelVoidsElement")}
    assert all(voids[c.Name] == terrain for c in cuts)
    assert "unhosted" not in (out / "build.log").read_text("utf-8")
    # the void is the viewer's to draw: the declared volumes are the model's
    k = 0.3048006096012192
    for c in cuts:
        gross = E.get_psets(c, qtos_only=True)["Qto_BaseQuantities"]["GrossVolume"]
        assert gross == pytest.approx(model.element(c.Name).quantities["volume_cf"] * k ** 3)


def test_the_terrain_leaves_the_volumes_and_the_haul_as_they_were(model):
    # as built before the plane wrote its terrain
    assert [round(r.cumulative_cy, 3) for r in model.mass_haul] == [
        328.116, 439.509, 366.388, 320.249, 239.668]
    assert {e.name: round(e.quantities["volume_cf"], 3) for e in model.elements
            if e.name.startswith("Cut ")} == {
        "Cut STA 10+00.00 to 11+00.00": 8942.793,
        "Cut STA 11+00.00 to 12+00.00": 4005.584,
        "Cut STA 12+00.00 to 13+00.00": 2212.546,
        "Cut STA 13+00.00 to 13+50.00": 886.26,
        "Cut STA 14+00.00 to 15+00.00": 1583.731}


def test_the_earthwork_carries_its_standard_set_and_the_haul(x3):
    import ifcopenshell.util.element as E

    from bimforge.author.alignment import sta
    f, out = x3
    rows = {(float(r["start"]), float(r["station"])): float(r["cumulative_cy"])
            for r in csv.DictReader(io.StringIO((out / "rc.masshaul.csv").read_text("utf-8")))}
    assert len(rows) == 5
    seen = set()
    for el in f.by_type("IfcProduct"):
        if not (el.Name or "").startswith(("Cut ", "Fill ")):
            continue
        qtos = E.get_psets(el, qtos_only=True)
        assert "Qto_BaseQuantities" in qtos
        if el.Name.startswith("Cut "):
            # it voids the plane's TERRAIN, so it is the cut its set is for
            assert el.is_a("IfcEarthworksCut")
            assert "Qto_EarthworksCutBaseQuantities" in qtos
        else:
            assert el.is_a("IfcEarthworksFill")
            assert "Qto_EarthworksFillBaseQuantities" in qtos
        ps = E.get_psets(el, psets_only=True)["BIMForge_MassHaul"]
        k = 0.3048006096012192
        key = (round(ps["StartStation"] / k, 6), round(ps["EndStation"] / k, 6))
        # the CSV rounds to 0.001 CY (0.0008 m3)
        assert ps["CumulativeVolume"] == pytest.approx(rows[key] * 27.0 * k ** 3, abs=8e-4)
        assert ps["StartStationText"] == sta(key[0]) and ps["EndStationText"] == sta(key[1])
        seen.add(key)
    assert seen == set(rows)


def test_the_ifc4_file_passes_the_schema_and_its_bodies_are_solid(tmp_path, model):
    from bimforge.author.gate import _ifc_solid_body_check, schema_issues
    from bimforge.bim.ifc_mesh import quiet_stdout
    f, out = _built(tmp_path, "IFC4")
    assert not schema_issues(f)
    # every product is a proxy here, so no class's standard set applies
    import ifcopenshell.util.element as E
    for prod in f.by_type("IfcBuildingElementProxy"):
        assert set(E.get_psets(prod, qtos_only=True)) <= {"Qto_BaseQuantities"}, prod.Name
    with quiet_stdout():
        assert _only_point_contacts(
            _ifc_solid_body_check(model, str(out / "rc.ifc"))) == []


US_FT = 0.30480060960121924


@pytest.fixture
def on_3dep(monkeypatch, tmp_path):
    """PARAMS on the same plane, served as a stubbed 3DEP grid (6 m cells)."""
    import numpy as np

    import bimforge.terrain as T
    import bimforge.terrain.attach as A
    from bimforge.terrain.grid import TerrainGrid

    def fake_fetch(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
        xmin, ymin, xmax, ymax = bbox_m            # ftUS: the model's own feet
        cols = int(round((xmax - xmin) / spacing_m))
        rows = int(round((ymax - ymin) / spacing_m))
        e = xmin + (np.arange(cols) + 0.5) * (xmax - xmin) / cols
        z = np.tile((300.0 + 0.05 * (e - E0)) * US_FT, (rows, 1))
        return TerrainGrid(z=z, bbox_m=bbox_m, spacing_m=spacing_m, crs_epsg=crs_epsg)

    monkeypatch.setattr(T, "fetch_3dep_dem", fake_fetch)
    monkeypatch.setattr(A, "fetch_3dep_dem", fake_fetch)
    p = copy.deepcopy(PARAMS)
    p["ground"] = {"source": "3dep", "cache": str(tmp_path / "rc"), "margin_ft": 0.0,
                   "spacing_m": 6.0}
    return p


def test_on_3dep_ground_the_cut_voids_the_terrain(on_3dep, tmp_path):
    """The cut is ground removed from the TERRAIN, so it voids it and is
    written as an IfcEarthworksCut, with no warning that it should."""
    import warnings

    import ifcopenshell

    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.families.road_corridor import build
    m = build(on_3dep, CTX)
    (terrain,) = [e for e in m.elements if e.predefined_type == "TERRAIN"]
    cuts = [e for e in m.elements if e.ifc_class == "IfcEarthworksCut"]
    assert cuts and all(e.voids == terrain.name for e in cuts)
    assert all(e.voids is None for e in m.elements if e not in cuts)
    out = tmp_path / "rc.ifc"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert {c.Name for c in f.by_type("IfcEarthworksCut")} == {e.name for e in cuts}
    assert all(r.RelatingBuildingElement.Name == terrain.name
               for r in f.by_type("IfcRelVoidsElement"))
    assert not f.by_type("IfcEarthworksElement", include_subtypes=False)
    import ifcopenshell.util.element as E
    for cut in f.by_type("IfcEarthworksCut"):
        assert "Qto_EarthworksCutBaseQuantities" in E.get_psets(cut, qtos_only=True)


def test_on_ifc4_a_cut_voids_nothing(on_3dep):
    """IFC4 has no IfcEarthworksCut to void with: the cut stays unhosted."""
    import dataclasses

    from bimforge.author.families.road_corridor import build
    m = build(on_3dep, dataclasses.replace(CTX, schema="IFC4"))
    assert any(e.predefined_type == "TERRAIN" for e in m.elements)
    assert all(e.voids is None for e in m.elements)


#: a level road on a plane that rises 1 in 20 along the road (north) and
#: falls 1 in 10 to its right (east): 18 to 20 ft of fill at 10+00, cut by
#: 14+00. 4:1 fill, 2:1 behind guardrail over 10 ft of it; rock 8 ft down
#: in cut; a wall wherever a slope would reach past 60 ft
STEEP = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0, "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 600.0}]},
    "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": 320.0, "g_in_pct": 0.0,
                            "g_out_pct": 0.0, "length_ft": 600.0,
                            "evc_station": 1600.0, "evc_elev": 320.0}]},
    "ground": {"source": "plane", "elevation": 300.0, "slope_n": 0.05, "slope_e": -0.1},
    "section": {
        "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                       {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                        "slope": -0.05}],
        "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                    {"name": "AB", "type": "CORE", "thickness": 1.0}],
        "side_slopes": {
            "cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
                    "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}},
            "fill": {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}},
            "daylight_limit_ft": 150, "footprint_ft": {"L": 60, "R": 60}}},
    "walls": "auto",
    "max_wall_height_ft": 20,
    "guardrail": {"design_speed_mph": 45},
    "stations": {"interval": 25, "band": 100},
}


@pytest.fixture(scope="module")
def steep_built():
    """STEEP built, with what the build wrote to stderr."""
    import contextlib

    from bimforge.author.families.road_corridor import build
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        m = build(copy.deepcopy(STEEP), CTX)
    return m, err.getvalue()


@pytest.fixture(scope="module")
def steep(steep_built):
    return steep_built[0]


def test_the_steep_road_finds_its_walls(steep):
    from bimforge.author.corridor.walls import STRUCTURE_HEADER, WALL_HEADER
    # Right of the road (x ft east, d = s - 1000) the ground is
    # 300 + 0.05 d - 0.1 x. The hinge (17 east, 320 - 0.49 - 1.4 = 318.11)
    # has 19.81 - 0.05 d ft of fill under it: over 10 ft to d = 196.2, so
    # 2:1 from the widening's hinge (20.94 east, 319.51 - 0.394 = 319.116):
    # 329.586 - 0.5 x meets the ground at x = 73.965 - 0.125 d, past the
    # 60 ft footprint to d = 111.7. So a wall from 10+00 (the run's first
    # station) to 11+11 (11+12 fits: x = 59.965). From d = 196.2 the fill is
    # 4:1, 322.36 - 0.25 x, meeting the ground at x = (22.36 - 0.05 d) / 0.15,
    # past 60 ft to d = 267.2: 12+00 to 12+50 fail; back from 12+00, 11+99 to
    # 11+97 fail (4:1) and 11+96 fits (10.01 ft of fill, 2:1, x = 49.47), so
    # the wall starts at 11+97; on from 12+50 it ends at 12+67 (12+68 fits).
    # Each wall's face is the shoulder edge (17 east, 319.51), 21.21 - 0.05 d
    # ft above the ground: 21.21 at 10+00, 15.66 at 11+11; 11.36 at 11+97,
    # 7.86 at 12+67. The first is over 20 ft: a structure candidate, its
    # ground lowest at 10+00 (the ground rises along the road). The left
    # side fits throughout (its 2:1 daylights by 49.31 ft, its 4:1 by
    # 45.57 ft, its rock cut by 55.6 ft)
    assert steep.tables["walls"] == (
        WALL_HEADER + "\n"
        "R,fill,1000.00,1111.00,17.00,15.66,21.21,yes,yes\n"
        "R,fill,1197.00,1267.00,17.00,7.86,11.36,yes,no\n")
    assert steep.tables["structures"] == (
        STRUCTURE_HEADER + "\n" "R,1000.00,1111.00,21.21,1000.00\n")


def test_the_steep_road_cuts_a_section_a_foot_outside_each_wall(steep):
    # the wall gaps' ends and their lead-ins' ends are stations (the first
    # wall starts at the run's start, so it has no lead-in there)
    ends = {s for el in courses(steep) for lf in el.geometry for s in lf.stations}
    assert {1000.0, 1111.0, 1112.0, 1196.0, 1197.0, 1267.0, 1268.0} <= ends


def _closed_earthwork(m) -> None:
    """Every cut and fill of `m` is closed bodies holding its volume."""
    from bimforge.author.primitives import _signed_volume
    earth = [e for e in m.elements if e.ifc_class.startswith("IfcEarthworks")]
    assert {e.ifc_class for e in earth} == {"IfcEarthworksCut", "IfcEarthworksFill"}
    for el in earth:
        got = 0.0
        for g in el.geometry:
            (d,) = g.body_solids()
            assert _manifold(d["tris"]), el.name
            v = d["verts"]
            got += _signed_volume([(v[a], v[b], v[c]) for a, b, c in d["tris"]])
        assert got == pytest.approx(el.quantities["volume_cf"], rel=1e-9)
        assert len(el.geometry) < 10, el.name


def test_the_steep_road_s_earthwork_is_closed(steep):
    _closed_earthwork(steep)


def test_without_walls_auto_a_slope_past_the_footprint_is_an_error():
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    del p["walls"]
    # at 10+00 the right 2:1 daylights 73.965 ft out
    with pytest.raises(ValueError, match=r"10\+00\.00: the R fill slope daylights "
                       r"73\.9\d ft out, past the R footprint of 60 ft"):
        build(p, CTX)


def test_walls_auto_with_no_failing_station_adds_no_walls():
    from bimforge.author.corridor.walls import STRUCTURE_HEADER, WALL_HEADER
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    # the 60 ft footprint was the only limit: without it every slope fits,
    # so walls: auto builds what the same spec without it builds
    del p["section"]["side_slopes"]["footprint_ft"]
    plain = copy.deepcopy(p)
    del plain["walls"]
    got, want = build(p, CTX), build(plain, CTX)
    # the guardrail block makes the guardrail table either way
    rail = want.tables.pop("guardrail")
    assert got.tables == {"walls": WALL_HEADER + "\n",
                          "structures": STRUCTURE_HEADER + "\n",
                          "guardrail": rail}
    assert want.tables == {}
    assert ([(e.name, e.quantities) for e in got.elements]
            == [(e.name, e.quantities) for e in want.elements])


def test_a_v1_corridor_makes_no_tables(model):
    assert model.tables == {}


def test_a_cut_wall_widens_only_its_side_s_shoulder():
    from bimforge.author.corridor.walls import STRUCTURE_HEADER, WALL_HEADER
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    # level ground rising 1 in 20 along the road, from 318 at 10+00: the
    # hinge (17 out, 318.11) is in cut past d = 2.2; the ditch's outer edge
    # is 24 out at 316.61, and the 2:1 backslope meets the ground
    # (318 + 0.05 d) at 24 + 2 (1.39 + 0.05 d) = 26.78 + 0.1 d ft: past the
    # R footprint of 40 ft from d = 132.2. So a cut wall from 11+33 (11+32
    # fits: 39.98 ft) to the run's end, beside a 10 ft shoulder: its edge
    # 22 out at 320 - 0.24 - 0.5 = 319.26, the ground 0.05 d - 1.26 above
    # it: 5.39 at 11+33, 28.74 at 16+00. The left reaches 86.78 ft at most
    p["ground"] = {"source": "plane", "elevation": 318.0, "slope_n": 0.05}
    p["section"]["side_slopes"]["footprint_ft"] = {"L": 150, "R": 40}
    m = build(p, CTX)
    assert m.tables["walls"] == (
        WALL_HEADER + "\n" "R,cut,1133.00,1600.00,22.00,5.39,28.74,no,no\n")
    assert m.tables["structures"] == STRUCTURE_HEADER + "\n"
    outer = {}
    for el in courses(m):
        if "shoulder" in el.name:
            for lf in el.geometry:
                side = lf.name[-1]
                for s, ring in zip(lf.stations, lf.rings):
                    outer[side, s] = ring[1][0]
    # the shoulder's outer edge: 10 ft wide over the wall, 5 ft a foot
    # before it and on the left throughout
    assert outer["R", 1132.0] == pytest.approx(-17.0)
    assert outer["R", 1133.0] == pytest.approx(-22.0)
    assert outer["R", 1400.0] == pytest.approx(-22.0)
    assert outer["R", 1600.0] == pytest.approx(-22.0)
    assert {round(u, 9) for (side, _s), u in outer.items() if side == "L"} == {17.0}
    _closed_earthwork(m)


def test_walls_auto_reads_the_ground_under_a_cut_wall_s_wider_shoulder():
    from bimforge.author.alignment import Alignment
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import ground_reach, per_component
    al_p = STEEP["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])

    class Grid:
        spacing_ft = 3.0

    c = parse(copy.deepcopy(STEEP), al.s_start, al.s_end)
    # a cut wall may widen the 5 ft shoulder to 10 ft on either side: the
    # lane in 4 cells, the shoulder in ceil(10 / 3) = 4; the reach 12 + 10
    # out to the hinge and the 150 ft daylight limit past it
    assert per_component(c, Grid()) == [4, 4]
    assert ground_reach(c) == pytest.approx(172.0)
    plain = copy.deepcopy(STEEP)
    del plain["walls"]
    c = parse(plain, al.s_start, al.s_end)
    assert per_component(c, Grid()) == [4, 2]
    assert ground_reach(c) == pytest.approx(167.0)


#: STEEP's road on ground that turns the left side from fill to cut at
#: 11+11.20, inside the right wall's lead-in (11+11 to 11+12)
TURN_IN_LEAD_IN = copy.deepcopy(STEEP)
TURN_IN_LEAD_IN["alignment"]["run"][0]["length"] = 300.0
TURN_IN_LEAD_IN["profile"]["curves"][0].update(length_ft=300.0, evc_station=1300.0)
TURN_IN_LEAD_IN["ground"] = {"source": "plane", "elevation": 310.17,
                             "slope_n": 0.05, "slope_e": -0.14}
TURN_IN_LEAD_IN["section"]["side_slopes"]["cut"].pop("rock")
TURN_IN_LEAD_IN["section"]["side_slopes"]["fill"] = {"ratio": 4.0}


def test_a_side_turning_inside_a_wall_s_lead_in_takes_no_section_there():
    from bimforge.author.families.road_corridor import build
    # the ground on the centreline is G = 310.17 + 0.05 d. The left hinge
    # (17 west, 318.11) meets the ground, G + 2.38, at d = 111.2. The right
    # 4:1, 322.36 - 0.25 x, meets the ground, G - 0.14 x, 60 ft out at
    # G = 315.76, d = 111.8: so a right fill wall from 10+00 to 11+11, its
    # lead-in to 11+12, its face (17 east, 319.51) 321.89 - G above the
    # ground: 11.72 at 10+00, 6.17 at 11+11. At 11+11.20 the right slope reaches 60.27 ft, past
    # the footprint: a section there would be refused, so the left side's
    # turn takes none (the strip across it is lofted from 11+11 to 11+12)
    m = build(copy.deepcopy(TURN_IN_LEAD_IN), CTX)
    assert m.tables["walls"].splitlines()[1:] == [
        "R,fill,1000.00,1111.00,17.00,6.17,11.72,yes,no"]
    stations = {s for el in courses(m) for lf in el.geometry for s in lf.stations}
    assert {1111.0, 1112.0} <= stations
    assert not [s for s in stations if 1111.0 < s < 1112.0]


def flat(points):
    return [c for p in points for c in p]


def test_the_steep_road_s_guardrail(steep_built):
    from bimforge.author.corridor import guardrail as gr
    steep, log = steep_built
    # The rail face is the shoulder edge, 17 ft out: L2 = 17 - 12 = 5 from
    # the edge of traveled way, 17 from the centreline. At 45 mph the lane
    # beside the rail needs 150 ft, the opposing lane 37.5 ft (by hand in
    # test_corridor_guardrail.py).
    # Left: 16.41 - 0.05 d ft of fill at the hinge (17 west, 318.11, over
    # ground 301.7 + 0.05 d), over 10 ft to d = 128.2: guarded at the
    # stations 10+00 to 11+25. Its own lane runs down-station: 150 ft past
    # 11+25 to 12+75; the opposing 37.5 ft before 10+00 is off the
    # alignment, so the run starts there, its terminal held at the
    # alignment's start (short_end). 275 ft is 22 whole elements and over
    # 150; the free end's nose is 12.5 ft on, at 12+87.50: 287.5 ft,
    # 287.5 / 6.25 = 46 spaces, 47 posts.
    # Right: guarded from 11+12 (past the first wall, 10+00 to 11+11) to
    # 11+96 (before the second, from 11+97); 150 ft before and 37.5 ft
    # after both reach a wall, so it ties into both with an AGT: 11+11 to
    # 11+97, 86 ft, held at both ends under 150 (below_minimum); 86 / 6.25
    # = 13.76, 14 posts
    assert steep.tables["guardrail"] == (
        gr.HEADER + "\n"
        "L,1000.00,1287.50,287.50,TERMINAL,TERMINAL,47,no,yes\n"
        "R,1111.00,1197.00,86.00,WALL,WALL,14,yes,no\n")
    left = steep.element("Guardrail L STA 10+00.00 to 12+87.50")
    assert (left.ifc_class, left.predefined_type) == ("IfcRailing", "GUARDRAIL")
    assert left.type_name == gr.TYPE_NAME
    assert left.quantities["length_ft"] == pytest.approx(287.5)
    # the band, 3 1/4 in by 12 1/4 in, swept 287.5 ft on a level tangent
    assert left.quantities["volume_cf"] == pytest.approx(
        3.25 * 12.25 / 144.0 * 287.5, rel=1e-9)
    assert left.psets["BIMForge_Guardrail"] == {
        "PostCount": 47, "StartTreatment": "TERMINAL", "EndTreatment": "TERMINAL",
        "Terminals": 2, "AGTTransitions": 0, "Anchors": 0}
    assert left.standard_qto == {"Qto_RailingBaseQuantities": {
        "Length": ("length", pytest.approx(287.5), "EndStation - StartStation")}}
    sweep = left.geometry
    assert (sweep.s0, sweep.s1) == (1000.0, 1287.5)
    assert flat(sweep.section) == pytest.approx(flat(gr.band("L", 17.0)))
    # the top of rail 31 in over the shoulder edge, which is 0.49 ft under
    # the PGL all along
    assert max(z for _x, z in sweep.section) == pytest.approx(31.0 / 12.0)
    assert {round(v, 9) for _s, v in sweep.camber} == {-0.49}
    right = steep.element("Guardrail R STA 11+11.00 to 11+97.00")
    assert flat(right.geometry.section) == pytest.approx(flat(gr.band("R", -17.0)))
    assert right.psets["BIMForge_Guardrail"] == {
        "PostCount": 14, "StartTreatment": "WALL", "EndTreatment": "WALL",
        "Terminals": 0, "AGTTransitions": 2, "Anchors": 0}
    assert right.spatial_part.name == "Segment 1"
    # each flag is a warning
    assert ("guardrail Guardrail R STA 11+11.00 to 11+97.00: 86.00 ft between "
            "fixed ends, under the 150 ft minimum" in log)
    assert ("guardrail Guardrail L STA 10+00.00 to 12+87.50: its terminal at "
            "STA 10+00.00 is held at the alignment's end" in log)
    assert log.count("guardrail Guardrail") == 2


def _verts(m, name: str) -> list:
    return [v for g in m.element(name).geometry for v in g.body_solids()[0]["verts"]]


def test_the_widening_runs_the_whole_rail_and_stops_at_its_end(steep):
    # past the guarded span the left is 4:1, the rail's widening behind it:
    # at 12+00 its hinge 20.94 west at 320 - 0.884 = 319.116 (model z
    # 19.116), and 4:1 from there meets the ground 310 + 0.1 x at
    # 319.116 + (20.94 - x) / 4 = 310 + 0.1 x, x = 14.351 / 0.35 = 41.003
    fill = _verts(steep, "Fill STA 12+00.00 to 13+00.00")

    def at(x, y, z):
        return any(abs(a - x) < 1e-3 and abs(b - y) < 1e-6 and abs(c - z) < 1e-3
                   for a, b, c in fill)

    assert at(-20.94, 200.0, 19.116)
    assert at(-41.003, 200.0, 14.1003)
    # a section at the rail's end, 12+87.50, still widened; at 13+00, past
    # it, the 4:1 runs from the hinge (17 west, 318.11) to the ground,
    # 315 + 0.1 x, at x = 7.36 / 0.35 = 21.029
    assert at(-20.94, 287.5, 19.116)
    assert not at(-20.94, 300.0, 19.116)
    assert at(-21.029, 300.0, 17.1029)


def test_bridge_rail_at_a_structure_gap_with_no_guarded_fill():
    # PARAMS (V1's road) with a guardrail block: no steep rule, so nothing
    # is guarded, but each end of the 13+50 to 14+00 structure gap takes
    # approach and departure rail from an AGT. Left: its own lane runs
    # down-station, so at 13+50 the traffic heading for the bridge is the
    # opposing lane's, 37.5 ft, made 150 ft up-station of the AGT (the
    # other end fixed), its nose 12.5 ft on at 11+87.50: 87.5 ft from the
    # listed left wall (10+50 to 11+00), so it runs on and ties into it:
    # 11+00 to 13+50, 250 ft, 41 posts. At 14+00 it is its own lane's,
    # 150 ft, cut at the alignment's end, 15+00: 100 ft held at both ends (below_minimum) and
    # its terminal held at the end (short_end), 17 posts. The right is the
    # mirror: 150 ft before 13+50 and its nose, 11+87.50 to 13+50; 37.5 ft
    # past 14+00, made 150, cut at 15+00
    from bimforge.author.corridor import guardrail as gr
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(PARAMS)
    p["guardrail"] = {"design_speed_mph": 45}
    m = build(p, CTX)
    assert m.tables["guardrail"] == (
        gr.HEADER + "\n"
        "L,1100.00,1350.00,250.00,WALL,AGT,41,no,no\n"
        "L,1400.00,1500.00,100.00,AGT,TERMINAL,17,yes,yes\n"
        "R,1187.50,1350.00,162.50,TERMINAL,AGT,27,no,no\n"
        "R,1400.00,1500.00,100.00,AGT,TERMINAL,17,yes,yes\n")
    rails = [e for e in m.elements if e.ifc_class == "IfcRailing"]
    assert [e.spatial_part.name for e in rails] == ["Segment 1", "Segment 2"] * 2
    # the rail follows the superelevation: the left shoulder edge is
    # 12 x -0.02 + 5 x -0.05 = -0.49 under normal crown, 12 x 0.04 - 0.25 =
    # 0.23 under the full super from 12+00 to 13+00
    camber = dict(m.element("Guardrail L STA 11+00.00 to 13+50.00").geometry.camber)
    assert camber[1100.0] == pytest.approx(-0.49)
    assert camber[1250.0] == pytest.approx(0.23)
    # the courses and earthwork: V1's names, in V1's order, then the rails
    v1 = build(copy.deepcopy(PARAMS), CTX)
    assert [e.name for e in m.elements][:len(v1.elements)] == [e.name for e in v1.elements]
    assert len(m.elements) == len(v1.elements) + 4
    _closed_earthwork(m)


def test_a_guardrail_block_with_no_guarded_fill_and_no_gap_lays_no_rail():
    from bimforge.author.corridor import guardrail as gr
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    del p["section"]["side_slopes"]["fill"]["steep"]
    del p["section"]["side_slopes"]["footprint_ft"]
    del p["walls"]
    m = build(p, CTX)
    assert m.tables == {"guardrail": gr.HEADER + "\n"}
    assert not [e for e in m.elements if e.ifc_class == "IfcRailing"]


def test_a_rail_over_a_moving_shoulder_edge_is_refused():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.guardrail import TERMINAL, RailRun
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import rail_element
    p = copy.deepcopy(STEEP)
    p["widths"] = [{"component": "shoulder", "side": "L", "at": [[1100, 5.0], [1200, 8.0]]}]
    al = Alignment(p["alignment"]["pob"], p["alignment"]["run"])
    prof = Profile(p["profile"]["curves"])
    c = parse(p, al.s_start, al.s_end)
    # the edge goes from 17 to 20 ft out under 10+00 to 12+75: 3 ft
    with pytest.raises(ValueError, match=r"Guardrail L STA 10\+00\.00 to 12\+75\.00: "
                       r"the shoulder edge moves 3\.00 ft under the rail"):
        rail_element(RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL), c, al, prof,
                     CTX, None)


def test_a_rail_near_a_cut_wall_ends_at_its_lead_in():
    from bimforge.author.corridor.guardrail import WALL
    from bimforge.author.corridor.params import Gap, parse
    from bimforge.author.families.road_corridor import lay_rails
    from bimforge.author.corridor.section import resolve
    al_s, al_e = 1000.0, 1600.0
    p = copy.deepcopy(STEEP)
    del p["section"]["side_slopes"]["footprint_ft"]
    c = parse(p, al_s, al_e).with_walls(
        [Gap(1400.0, 1450.0, "wall", "L", None, auto="cut")])
    # the left guarded at 10+00 to 11+25 (STEEP's ground) runs down-station
    # to 12+75 and its nose to 12+87.50: within 200 ft of the cut wall, so
    # it ties in, at the foot before the wall where the 10 ft shoulder's
    # widening starts (13+99), not at the wall (14+00)
    stations = c.stations(al_s, al_e)

    def ground_dz(s, u, v):
        # STEEP's plane, on the level road at 320: x east = -u
        return 300.0 + 0.05 * (s - 1000.0) + 0.1 * u - (320.0 + v)

    secs = [resolve(c, s, ground_dz) for s in stations]
    (left,) = [r for r in lay_rails(c, [secs]) if r.side == "L"]
    assert (left.start, left.end, left.end_end) == (1000.0, 1399.0, WALL)


@pytest.mark.parametrize("schema", ["IFC4X3_ADD2", "IFC4"])
def test_the_steep_road_s_rails_are_ifc_guardrails(steep, tmp_path, schema):
    import dataclasses

    import ifcopenshell
    import ifcopenshell.util.element as E

    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.gate import schema_issues
    from bimforge.author.model import StructureModel
    # IfcRailing GUARDRAIL is in both schemas: no proxy fallback in IFC4
    one = StructureModel("rails", dataclasses.replace(CTX, schema=schema))
    for el in steep.elements:
        if el.ifc_class == "IfcRailing":
            one.add(el)
    out = tmp_path / "rails.ifc"
    emit_ifc(one, str(out))
    f = ifcopenshell.open(str(out))
    assert not schema_issues(f)
    rails = f.by_type("IfcRailing")
    assert len(rails) == 2
    for rail in rails:
        assert E.get_predefined_type(rail) == "GUARDRAIL"
        assert E.get_type(rail).Name == "Midwest guardrail system"
        assert "Qto_RailingBaseQuantities" in E.get_psets(rail, qtos_only=True)


def test_an_ifc4x3_build_with_rail_passes_the_gate(tmp_path):
    import contextlib

    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import _ifc_solid_body_check, schema_issues
    from bimforge.bim.ifc_mesh import quiet_stdout
    paycodes = PAYCODES.replace(
        "groups:\n", '  - {match: "(?i)^Guardrail ", group: rc_rail}\ngroups:\n'
                     "  rc_rail: {measure: Length}\n") + (
        '  RC-RAIL: {group: rc_rail, measure: Length, unit: LF, item_number: "0003",\n'
        '            description: "Guardrail"}\n')
    (tmp_path / "rc.paycodes.yaml").write_text(paycodes, "utf-8")
    params = copy.deepcopy(PARAMS)
    params["guardrail"] = {"design_speed_mph": 45}
    spec = {"family": "road-corridor", "params": params,
            "paycodes": "./rc.paycodes.yaml",
            "outputs": {"ifc": "out/rc.ifc"},
            "project": {"name": "Corridor fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": "IFC4X3_ADD2", "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre gate and the post gate both passed
        assert build_from_spec(str(path)) == 0, err.getvalue()
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.ifc"))
    assert not schema_issues(f)
    assert len(f.by_type("IfcRailing")) == 4
    from bimforge.author.families.road_corridor import build
    with quiet_stdout():
        found = _only_point_contacts(_ifc_solid_body_check(
            build(copy.deepcopy(params), CTX), str(tmp_path / "out" / "rc.ifc")))
    # only the courses' sectioned caps (test_every_body_is_solid_but_...)
    assert all("(IfcCourse)" in msg for msg in found), found


def test_a_slope_the_widening_pushes_past_the_footprint_takes_a_wall():
    from bimforge.author.corridor import guardrail as gr
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    p["section"]["side_slopes"]["footprint_ft"]["L"] = 47
    # Left (x west, d = s - 1000): the ground is 300 + 0.05 d + 0.1 x, the
    # widening's hinge 20.94 west at 319.116.
    # First pass: the guarded 2:1 from the widening's hinge, 329.586 - 0.5 x,
    # meets the ground at x = (29.586 - 0.05 d) / 0.6, past 47 ft to
    # d = 27.72: a fill wall from 10+00 to 10+27 (10+28 fits, 46.98 ft).
    # The rail: guarded 10+28 to 11+25, 150 ft on and 37.5 ft back, ties
    # into that wall at 10+27, made 250 ft (whole elements) to 12+77 and its
    # nose to 12+89.50. Under it, past the guarded span (d over 128.2), the
    # 4:1 runs from the widening's hinge, 324.351 - 0.25 x, to
    # x = (24.351 - 0.05 d) / 0.35: 48.15 ft at 11+50 (42.46 without the
    # widening), past 47 ft to d = 158.02. So a second fill wall, 11+29
    # (11+28 is guarded, 10.01 ft of fill: 2:1, 38.04 ft) to 11+58 (11+59
    # fits, 46.86 ft). The rail laid again runs wall to wall: 10+27 to
    # 11+29, 102 ft, held short of 150 at both ends; 102 / 6.25 = 16.3, 17
    # posts. Past 11+58 the left is not guarded and has no rail. Each wall's
    # face, the shoulder edge (17 west, 319.51), is 17.81 - 0.05 d above
    # the ground: 17.81 and 16.46; 11.36 and 9.91
    m = build(p, CTX)
    assert m.tables["guardrail"] == (
        gr.HEADER + "\n"
        "L,1027.00,1129.00,102.00,WALL,WALL,17,yes,no\n"
        "R,1111.00,1197.00,86.00,WALL,WALL,14,yes,no\n")
    rows = m.tables["walls"].splitlines()
    assert "L,fill,1000.00,1027.00,17.00,16.46,17.81,yes,no" in rows
    assert "L,fill,1129.00,1158.00,17.00,9.91,11.36,yes,no" in rows
    _closed_earthwork(m)


def test_without_walls_auto_a_widening_past_the_footprint_says_what_to_do():
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    del p["walls"]
    # the left's guarded 2:1 reaches 49.31 ft at most and its 4:1 without
    # the widening 40.7 ft: both fit 49.5 ft. Under the rail, the 4:1 from
    # the widening's hinge reaches (24.351 - 0.05 d) / 0.35 ft: 51.00 ft at
    # 11+30, the first station (10 ft apart) past the guarded span. The road
    # ends at 13+00, before the left's rock cut (55.6 ft)
    p["alignment"]["run"][0]["length"] = 300.0
    p["profile"]["curves"][0].update(length_ft=300.0, evc_station=1300.0)
    p["section"]["side_slopes"]["footprint_ft"] = {"L": 49.5}
    p["stations"]["interval"] = 10
    with pytest.raises(ValueError, match=r"guardrail: the widening behind the rail "
                       r"at 11\+30\.00 pushes the slope out: .*daylights 51\.00 ft "
                       r"out.*; list a wall gap there, widen footprint_ft, or set "
                       r"walls: auto"):
        build(p, CTX)


def test_rail_stations_merge_once_within_a_tolerance():
    from bimforge.author.families.road_corridor import merge_stations
    # two rails ending at one station, one of them also a station already
    assert merge_stations([1500.0, 1525.0, 1550.0],
                          [1537.5, 1537.5, 1537.5 + 1e-9, 1525.0 + 1e-8]) == [
        1500.0, 1525.0, 1537.5, 1550.0]


def test_the_v1_1_preview_spec_builds_through_the_gate(tmp_path):
    # the shipped example with V1.1's slope rules, walls: auto and guardrail
    # beside its bridge and listed wall: two rails ending at one station
    # once cut the same section twice
    import contextlib
    import pathlib
    import shutil

    import yaml

    from bimforge.author.families.registry import build_from_spec
    here = pathlib.Path(__file__).parent / "fixtures" / "road-corridor-v11-preview"
    spec = yaml.safe_load((here / "road-corridor.spec.yaml").read_text("utf-8"))
    spec["outputs"] = {"ifc": "out/rc.ifc"}
    shutil.copy(here / "road-corridor.paycodes.yaml", tmp_path)
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre gate and the post gate both passed
        assert build_from_spec(str(path)) == 0, err.getvalue()
    assert "mesh did not sew" not in err.getvalue()


def test_a_course_declares_its_exact_volume_and_its_mesh_is_held_to_it(model):
    from bimforge.author.corridor.loft import pappus
    from bimforge.author.gate import check_arc_faceting
    for el in courses(model):
        assert el.quantities["volume_cf"] == pytest.approx(
            pappus(el.geometry).volume_cf, rel=1e-12), el.name
        assert el.standard_qto["Qto_CourseBaseQuantities"]["Volume"][1] == \
            el.quantities["volume_cf"]
    # each loft's mesh within 0.5% of its exact volume (the pre gate's check)
    assert check_arc_faceting(model) == []


# -- V1.1: dictionary classes, BIMForge_Dimensions and Formulas -------------
STEEP_PAYCODES = """\
rules:
  - {match: "(?i)^(HMA|AB) ", group: rc_pave}
  - {match: "(?i)^(Cut|Fill) ", group: rc_earth}
  - {match: "(?i)^Guardrail ", group: rc_mgs}
groups:
  rc_pave: {measure: GrossVolume}
  rc_earth: {measure: GrossVolume}
  rc_mgs: {measure: Length}
codes:
  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY, item_number: "0001",
            description: "Pavement courses"}
  RC-EARTH: {group: rc_earth, measure: GrossVolume, unit: CY, item_number: "0002",
             description: "Earthwork"}
  RC-MGS: {group: rc_mgs, measure: Length, unit: LF, item_number: "0003",
           description: "Midwest guardrail system"}
"""


def _spec_path(tmp_path, params, outputs, schema="IFC4X3_ADD2"):
    import yaml
    (tmp_path / "rc.paycodes.yaml").write_text(STEEP_PAYCODES, "utf-8")
    spec = {"family": "road-corridor", "params": copy.deepcopy(params),
            "paycodes": "./rc.paycodes.yaml",
            "outputs": {"ifc": "out/rc.ifc", **outputs},
            "project": {"name": "Corridor fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": schema, "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    return path


def _built_from(tmp_path, params, outputs=None):
    import contextlib

    import ifcopenshell

    from bimforge.author.families.registry import build_from_spec
    path = _spec_path(tmp_path, params, outputs or {})
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre and post gates passed, the formula check among them
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    return ifcopenshell.open(str(tmp_path / "out" / "rc.ifc")), tmp_path / "out"


@pytest.fixture(scope="module")
def steep_x3(tmp_path_factory):
    return _built_from(tmp_path_factory.mktemp("steep"), STEEP)


CORRIDOR_CLASSES = {"road-corridor-course", "road-corridor-cut",
                    "road-corridor-fill", "road-corridor-guardrail"}


def test_every_corridor_element_is_classed_and_dimensioned(steep_x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    from bimforge.bim.ifc_takeoff import family_class_of
    f, _out = steep_x3
    seen = set()
    for el in f.by_type("IfcElement"):
        if el.is_a("IfcGeographicElement"):
            continue                                     # the TERRAIN
        cls = family_class_of(el)
        assert cls and cls["code"] in CORRIDOR_CLASSES, el.Name
        dims = dict(E.get_pset(el, fd.DIMENSIONS) or {})
        dims.pop("id", None)
        assert set(fd.required_dimensions(cls["code"])) <= set(dims) \
            <= set(fd.dimensions(cls["code"])), el.Name
        assert dims["StartStationText"] == el.Name.split("STA ")[1].split(" to ")[0]
        seen.add(cls["code"])
    assert seen == CORRIDOR_CLASSES
    # the steep road's cut has rock 8 ft down, so its cut carries RockDepth;
    # its soil slope is 2:1. The fill under the guarded span is 2:1 too
    cuts = f.by_type("IfcEarthworksCut")
    assert cuts
    for cut in cuts:
        d = E.get_pset(cut, fd.DIMENSIONS)
        assert d["RockDepth"] == pytest.approx(8.0 * US_FT)
        assert d["SlopeRatio"] == pytest.approx(2.0)
        assert 0.0 < d["MeanDepth"] <= d["MaxDepth"]
    fill = next(e for e in f.by_type("IfcEarthworksFill")
                if e.Name == "Fill STA 10+00.00 to 11+00.00")
    assert E.get_pset(fill, fd.DIMENSIONS)["SlopeRatio"] == pytest.approx(2.0)


def test_the_left_rail_s_dimensions_and_length(steep_x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    f, _out = steep_x3
    rail = next(e for e in f.by_type("IfcRailing") if e.Name.startswith("Guardrail L "))
    d = E.get_pset(rail, fd.DIMENSIONS)
    assert d["StartStation"] == pytest.approx(1000.0 * US_FT)
    assert d["EndStation"] == pytest.approx(1287.5 * US_FT)
    assert (d["StartStationText"], d["EndStationText"]) == ("10+00.00", "12+87.50")
    assert d["RailHeight"] == pytest.approx(31.0 / 12.0 * US_FT)
    assert d["PostSpacing"] == pytest.approx(6.25 * US_FT)
    q = E.get_psets(rail, qtos_only=True)["Qto_RailingBaseQuantities"]
    assert q["Length"] == pytest.approx(287.5 * US_FT)
    assert E.get_type(rail).Name == "Midwest guardrail system"


def _course_volume(course):
    (vol,) = [q for r in course.IsDefinedBy
              if r.RelatingPropertyDefinition.is_a("IfcElementQuantity")
              and r.RelatingPropertyDefinition.Name == "Qto_CourseBaseQuantities"
              for q in r.RelatingPropertyDefinition.Quantities if q.Name == "Volume"]
    return vol


def test_every_formula_holds_and_every_steep_course_is_its_path_box(steep_x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    from bimforge.author.gate import _ifc_formula_check
    f, out = steep_x3
    assert _ifc_formula_check(None, str(out / "rc.ifc")) == []
    found = {(qs.Name, q.Name, q.Formula) for qs in f.by_type("IfcElementQuantity")
             for q in qs.Quantities if getattr(q, "Formula", None)}
    for qset in ("Qto_CourseBaseQuantities", "Qto_EarthworksCutBaseQuantities",
                 "Qto_EarthworksFillBaseQuantities", "Qto_RailingBaseQuantities"):
        assert (qset, "Length", "EndStation - StartStation") in found
    # no volume formula on earthwork: its section changes at every station
    assert not [x for x in found if x[0].startswith("Qto_Earthworks")
                and x[1] != "Length"]
    # the steep road is a level tangent at constant widths: every course is
    # its path box
    for course in f.by_type("IfcCourse"):
        assert _course_volume(course).Formula == "PathLength * Width * Thickness",             course.Name
    # the lane, centroid (0, -0.32), on the level tangent: its path is the
    # band's 100 ft (a dimension is written to 1e-9 m)
    lane = next(c for c in f.by_type("IfcCourse")
                if c.Name == "HMA lane STA 10+00.00 to 11+00.00")
    d = E.get_pset(lane, fd.DIMENSIONS)
    assert d["PathLength"] == pytest.approx(100.0 * US_FT, abs=1e-9)
    assert d["Offset"] == pytest.approx(0.0, abs=1e-9)
    assert d["Width"] == pytest.approx(24.0 * US_FT)
    assert d["Thickness"] == pytest.approx(0.4 * US_FT)


def test_courses_on_a_curve_and_a_grade_are_their_path_boxes(x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    from bimforge.author.gate import _ifc_formula_check
    f, out = x3
    assert _ifc_formula_check(None, str(out / "rc.ifc")) == []
    # PARAMS curves at 500 ft and climbs 1% through two superelevation runs,
    # every course at a constant width and both sides alike, so each
    # course's centroid is on the centreline (Offset 0) and the curve does
    # not lengthen its path: every course carries the formula
    courses_ = f.by_type("IfcCourse")
    assert courses_
    for course in courses_:
        assert _course_volume(course).Formula == "PathLength * Width * Thickness", \
            course.Name
        d = E.get_pset(course, fd.DIMENSIONS)
        assert {"Offset", "PathLength", "Width"} <= set(d)
        assert d["Offset"] == pytest.approx(0.0, abs=1e-9), course.Name


def _lopsided(radius, delta, grade_pct):
    """A 300 ft road whose middle 100 ft (11+00 to 12+00) is a right curve
    of `radius`, on a constant `grade_pct`, its shoulder 1 ft on the left
    and 9 ft on the right: the shoulder element's centroid well off the
    line."""
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(PARAMS)
    p["alignment"]["run"] = [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
        {"kind": "curve", "delta": delta, "radius": radius, "turn": "R",
         "length": 100.0},
        {"kind": "tangent", "bearing": f"N {delta} E", "length": 100.0}]
    p["profile"]["curves"] = [{"bvc_station": 1000.0, "bvc_elev": 300.0,
                               "g_in_pct": grade_pct, "g_out_pct": grade_pct,
                               "length_ft": 300.0, "evc_station": 1300.0,
                               "evc_elev": 300.0 + 3.0 * grade_pct}]
    p["ground"] = {"source": "plane", "elevation": 290.0}
    p["superelevation"] = [[1000, -0.02, -0.02], [1300, -0.02, -0.02]]
    p["gaps"] = []
    p["widths"] = [
        {"component": "shoulder", "side": "L", "at": [[1000, 1.0], [1300, 1.0]]},
        {"component": "shoulder", "side": "R", "at": [[1000, 9.0], [1300, 9.0]]}]
    return build(p, CTX)


def _box_over(el):
    """PathLength x Width x Thickness over the declared volume, less one."""
    q = el.standard_qto["Qto_CourseBaseQuantities"]
    return (el.dimensions["PathLength"] * el.dimensions["Width"] * q["Thickness"][1]
            / q["Volume"][1] - 1.0)


def test_a_lopsided_shoulder_on_a_gentle_curve_takes_the_formula():
    from bimforge.author.corridor import dimensions as dims
    m = _lopsided(500.0, "11-27-33", 1.0)
    el = m.element("HMA shoulder STA 11+00.00 to 12+00.00")
    # 1 ft left at u = 12.5 and 9 ft right at u = -16.5, 0.4 ft thick:
    # Offset = (1 x 12.5 - 9 x 16.5) / 10 = -13.6 ft (RT), inside the right
    # curve. kappa = -1/500, g = 0.01: the centroid's speed along the 3D
    # tangent is sqrt(1 + g^2) - 13.6 / 500 cos(gamma) = 0.972815, its
    # sideways speed 13.6 / 500 sin(gamma) = 2.7199e-4, so the path box is
    # over by (2.7199e-4)^2 / (2 x 0.972815^2) = 3.9e-8: under 1e-6
    assert el.dimensions["Offset"] == pytest.approx(-13.6, abs=1e-9)
    assert el.dimensions["Width"] == pytest.approx(10.0)
    assert _box_over(el) == pytest.approx(3.9e-8, rel=0.02)
    assert el.standard_qto["Qto_CourseBaseQuantities"]["Volume"][2] == dims.VOLUME


def test_a_lopsided_shoulder_on_a_tight_steep_curve_does_not():
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.gate import FORMULA_TOLERANCE
    m = _lopsided(300.0, "19-05-55", 6.0)
    el = m.element("HMA shoulder STA 11+00.00 to 12+00.00")
    # kappa = -1/300, g = 0.06: sqrt(1.0036) = 1.001798, cos(gamma) =
    # 0.998205, sin(gamma) = 0.059892. Along the 3D tangent 1.001798 -
    # 13.6 / 300 x 0.998205 = 0.956546; sideways 13.6 / 300 x 0.059892 =
    # 2.7151e-3 (and 0.645 / 300 x 0.059892 = 1.29e-4 from the centroid's
    # height): over by (2.7151e-3^2 + 1.29e-4^2) / (2 x 0.956546^2) =
    # 4.04e-6, past the gate's 1e-6, so the family leaves the formula out
    assert el.dimensions["Offset"] == pytest.approx(-13.6, abs=1e-9)
    assert _box_over(el) == pytest.approx(4.04e-6, rel=0.01)
    assert _box_over(el) > FORMULA_TOLERANCE
    assert len(el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]) == 2
    # the lane on the same curve is centred (Offset 0), and the shoulder on
    # the tangents either side has no curve: both keep it
    for name in ("HMA lane STA 11+00.00 to 12+00.00",
                 "HMA shoulder STA 10+00.00 to 11+00.00",
                 "AB shoulder STA 12+00.00 to 13+00.00"):
        assert m.element(name).standard_qto["Qto_CourseBaseQuantities"][
            "Volume"][2] == dims.VOLUME, name
    # Length holds on the curve as anywhere: by station
    assert el.standard_qto["Qto_CourseBaseQuantities"]["Length"] == (
        "length", pytest.approx(100.0), dims.LENGTH)


def test_a_widening_shoulder_takes_the_trapezoid():
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.families.road_corridor import build
    from bimforge.author.gate import FORMULA_TOLERANCE, formula_value
    p = copy.deepcopy(PARAMS)
    p["widths"] = [{"component": "shoulder", "side": "R",
                    "at": [[1000, 5.0], [1100, 10.0]]}]
    el = build(p, CTX).element("HMA shoulder STA 10+00.00 to 11+00.00")
    # both shoulders together: 5 + 5 = 10 ft at 10+00, 5 + 10 = 15 ft at 11+00
    assert (el.dimensions["StartWidth"], el.dimensions["EndWidth"]) == \
        pytest.approx((10.0, 15.0))
    assert "Width" not in el.dimensions
    # on the tangent at 1%: PathLength = 100 x sqrt(1.0001) = 100.005 ft;
    # Volume = 0.4 x 100.005 x (10 + 15) / 2 = 500.025 cf, the trapezoid exactly
    assert el.dimensions["PathLength"] == pytest.approx(100.0 * 1.0001 ** 0.5, rel=1e-9)
    vol = el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]
    assert vol[1] == pytest.approx(500.025, rel=1e-6)
    assert vol[2] == dims.TRAPEZOID
    assert formula_value(dims.TRAPEZOID, {**el.dimensions, "Thickness": 0.4}) == \
        pytest.approx(vol[1], rel=FORMULA_TOLERANCE)
    # its Qto Width is the band's mean, weighted by length: 12.5 ft
    assert el.standard_qto["Qto_CourseBaseQuantities"]["Width"][1] == pytest.approx(12.5)


def test_the_course_volume_entry():
    from bimforge.author.corridor import dimensions as dims
    # Task 10's shoulder on the curve: 89.8141498 x 5 x 0.4 is 1.6e-7 over
    # its 179.6282711 cf: the box holds
    assert dims.course_volume(179.6282711, 89.8141498, [5.0, 5.0, 5.0], 0.4) == (
        {"Width": 5.0}, ("volume", 179.6282711, dims.VOLUME))
    # a volume the box misses gets none
    assert dims.course_volume(180.0, 89.8141498, [5.0, 5.0, 5.0], 0.4) == (
        {"Width": 5.0}, ("volume", 180.0))
    # 100 x (10 + 15) / 2 x 0.4 = 500
    assert dims.course_volume(500.0, 100.0, [10.0, 12.5, 15.0], 0.4) == (
        {"StartWidth": 10.0, "EndWidth": 15.0}, ("volume", 500.0, dims.TRAPEZOID))
    assert dims.stations(1000.0, 1287.5) == {
        "StartStation": 1000.0, "EndStation": 1287.5,
        "StartStationText": "10+00.00", "EndStationText": "12+87.50"}


def test_bidsheet_reads_the_dimensions_and_not_the_station_texts(steep_x3):
    from bimforge.bim.model_elements import plan_modelled_elements
    _f, out = steep_x3
    plan = plan_modelled_elements(str(out / "rc.ifc"), all_elements=True)
    assert not [w for w in plan["warnings"] if "StationText" in w]
    rail = next(e for e in plan["elements"] if e["name"].startswith("Guardrail L "))
    assert rail["parameters"]["StartStation"] == {"value": 1000.0, "unit": "FT"}
    assert rail["parameters"]["RailHeight"] == {
        "value": pytest.approx(31.0 / 12.0), "unit": "FT"}
    assert "StartStationText" not in rail["parameters"]


def test_the_rail_type_is_the_dictionary_s_guardrail_class():
    from bimforge.author import family_dictionary as fd
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor import guardrail as gr
    assert gr.TYPE_NAME == fd.type_name(dims.GUARDRAIL)


def test_a_band_mean_is_weighted_by_length():
    from bimforge.author.corridor import dimensions as dims
    # 8 ft over the first 90 ft, rising to 18 ft over the last 10:
    # (90 x 8 + 10 x 13) / 100 = 8.5, not the stations' mean 11.33
    assert dims.band_mean([1000.0, 1090.0, 1100.0], [8.0, 8.0, 18.0]) == \
        pytest.approx(8.5)


def test_a_fill_with_no_fill_side_has_no_slope_ratio(model):
    # PARAMS from 10+00 to 11+00: the ground rises east 5%, so the right is
    # cut, and the left is cut to 10+50 and a wall from there: the band's
    # fill is under the road only, with no fill slope to state
    el = model.element("Fill STA 10+00.00 to 11+00.00")
    assert "SlopeRatio" not in el.dimensions
    assert {"MaxDepth", "MeanDepth", "StartStation", "EndStation"} <= set(el.dimensions)
    # the next band's left is a 2:1 fill slope
    assert model.element("Fill STA 11+00.00 to 12+00.00").dimensions[
        "SlopeRatio"] == pytest.approx(2.0)


def _dims_of(el):
    """{name: IfcPropertySingleValue} of el's BIMForge_Dimensions."""
    from bimforge.author import family_dictionary as fd
    for rel in el.IsDefinedBy or ():
        pset = rel.RelatingPropertyDefinition
        if pset.is_a("IfcPropertySet") and pset.Name == fd.DIMENSIONS:
            return {x.Name: x for x in pset.HasProperties}
    return {}


def test_each_dimension_is_written_as_its_measure_and_a_taper_as_its_ends(tmp_path):
    import ifcopenshell.util.element  # noqa: F401

    from bimforge.author import family_dictionary as fd
    from bimforge.author.gate import _ifc_formula_check
    from bimforge.bim.ifc_takeoff import family_class_of
    p = copy.deepcopy(PARAMS)
    p["widths"] = [{"component": "shoulder", "side": "R",
                    "at": [[1000, 5.0], [1100, 10.0]]}]
    f, out = _built_from(tmp_path, p)
    assert _ifc_formula_check(None, str(out / "rc.ifc")) == []
    kinds = {"IfcLengthMeasure": float, "IfcRatioMeasure": float, "IfcLabel": str}
    checked = set()
    for el in f.by_type("IfcElement"):
        cls = family_class_of(el)
        if cls is None:
            continue                                     # the TERRAIN
        for code, prop in _dims_of(el).items():
            nv = prop.NominalValue
            assert nv.is_a() == fd.measure(code)[0], (el.Name, code)
            assert isinstance(nv.wrappedValue, kinds[nv.is_a()]), (el.Name, code)
            checked.add((code, nv.is_a()))
    assert {("SlopeRatio", "IfcRatioMeasure"), ("StartStationText", "IfcLabel"),
            ("PathLength", "IfcLengthMeasure")} <= checked
    taper = next(c for c in f.by_type("IfcCourse")
                 if c.Name == "HMA shoulder STA 10+00.00 to 11+00.00")
    d = {n: x.NominalValue.wrappedValue for n, x in _dims_of(taper).items()}
    # 10 ft at 10+00 and 15 ft at 11+00, both shoulders together, in metres
    assert (d["StartWidth"], d["EndWidth"]) == pytest.approx((10.0 * US_FT, 15.0 * US_FT))
    assert "Width" not in d
    assert _course_volume(taper).Formula == \
        "PathLength * (StartWidth + EndWidth) / 2 * Thickness"


def test_the_tables_are_written_where_the_spec_says(tmp_path):
    from bimforge.author.families.road_corridor import build
    outputs = {key: f"out/rc.{key}.csv" for key in ("walls", "structures", "guardrail")}
    _f, out = _built_from(tmp_path, STEEP, outputs)
    m = build(copy.deepcopy(STEEP), CTX)
    for key in outputs:
        assert (out / f"rc.{key}.csv").read_text("utf-8") == m.tables[key]


def test_a_corridor_without_walls_auto_has_no_wall_table(tmp_path):
    from bimforge.author.families.registry import build_from_spec
    path = _spec_path(tmp_path, PARAMS, {"walls": "out/rc.walls.csv"})
    with pytest.raises(ValueError, match=r"outputs\.walls.*road-corridor.*no walls table"):
        build_from_spec(str(path), check_only=True)
    assert not (tmp_path / "out").exists()


def test_check_only_writes_no_table(tmp_path):
    from bimforge.author.families.registry import build_from_spec
    path = _spec_path(tmp_path, STEEP, {"guardrail": "out/rc.guardrail.csv"})
    assert build_from_spec(str(path), check_only=True) == 0
    assert not (tmp_path / "out").exists()


def test_the_example_with_a_wall_ending_on_its_bridge_builds(tmp_path):
    # with the left footprint at 64 ft (the example has 66), the widening
    # behind the left bridge-approach rail adds an automatic fill wall
    # 16+76 to 17+00, ending on the bridge gap: the rail re-laid there has
    # no length left (the wall's barrier meets the bridge) and is dropped,
    # and the build passes both gates
    import contextlib
    import pathlib
    import shutil

    import yaml

    from bimforge.author.families.registry import build_from_spec
    here = pathlib.Path(__file__).resolve().parents[1] / "examples"
    spec = yaml.safe_load((here / "road-corridor.spec.yaml").read_text("utf-8"))
    spec["params"]["section"]["side_slopes"]["footprint_ft"]["L"] = 64
    spec["outputs"] = {"ifc": "out/rc.ifc", "walls": "out/rc.walls.csv",
                       "guardrail": "out/rc.guardrail.csv"}
    shutil.copy(here / "road-corridor.paycodes.yaml", tmp_path)
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre gate and the post gate both passed
        assert build_from_spec(str(path)) == 0, err.getvalue()
    walls = list(csv.DictReader(io.StringIO(
        (tmp_path / "out" / "rc.walls.csv").read_text("utf-8"))))
    assert any(w["side"] == "L" and float(w["end"]) == pytest.approx(1700.0)
               for w in walls), walls
    rails = list(csv.DictReader(io.StringIO(
        (tmp_path / "out" / "rc.guardrail.csv").read_text("utf-8"))))
    assert rails and all(float(r["length_ft"]) > 0.0 for r in rails)


def test_each_length_of_need_reads_the_rail_face_where_it_is_laid():
    # STEEP's level tangent run on to 26+00, a bridge at 24+00 to 24+50, the
    # right shoulder widened from 5 ft to 10 ft over 15+00 to 16+00, 50 mph.
    # At 24+00 the face is 22 ft out: L2 = 10, so the right lane's (up-
    # station) need is (20 - 10) x 230 / 20 = 115, 10 elements, 125 ft:
    # 22+75 to the AGT, made 150 ft to 22+50, its nose 22+37.50: 162.5 ft.
    # A guarded span at 11+00 to 12+00, where the face is 17 ft out, must
    # not change it (read there, L2 = 5 makes it 175 ft and the rail
    # 187.5). That span's own rail: back 175 ft, cut at the alignment's
    # start, and on 37.5 ft (L = 17) to 12+37.50: 237.5 ft, 19 whole
    # elements, its nose 12.5 ft on: 10+00 to 12+50. A widening under a
    # rail stays refused (test_a_rail_over_a_moving_shoulder_edge_is_refused)
    from types import SimpleNamespace as NS

    from bimforge.author.corridor.guardrail import AGT, TERMINAL
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import lay_rails
    p = copy.deepcopy(STEEP)
    p["alignment"]["run"][0]["length"] = 1600.0
    p["profile"]["curves"][0].update(length_ft=1600.0, evc_station=2600.0)
    p["gaps"] = [{"from": 2400, "to": 2450, "kind": "structure"}]
    p["widths"] = [{"component": "shoulder", "side": "R", "at": [[1500, 5.0], [1600, 10.0]]}]
    del p["walls"]
    p["guardrail"] = {"design_speed_mph": 50}
    c = parse(p, 1000.0, 2600.0)

    def run(guarded):
        return [NS(s=float(s), sides={"L": NS(guarded=False),
                                      "R": NS(guarded=guarded(s))})
                for s in range(1000, 2401, 25)]

    def bridge(rails):
        (r,) = [r for r in rails if r.side == "R" and r.end_end == AGT]
        return (r.start, r.end, r.start_end)

    plain = lay_rails(c, [run(lambda s: False)])
    spanned = lay_rails(c, [run(lambda s: 1100 <= s <= 1200)])
    assert bridge(plain) == bridge(spanned) == (2237.5, 2400.0, TERMINAL)
    assert [(r.start, r.end) for r in spanned if r.end_end != AGT] == [(1000.0, 1250.0)]
