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
