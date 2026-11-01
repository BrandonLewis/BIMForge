"""bimforge.author.placement: shared alignments and the spec placement block."""
from __future__ import annotations

import math
import uuid

import pytest
import yaml

from bimforge.author.model import Element, StructureModel
from bimforge.author.placement import (adopt_shared, apply_placement,
                                       load_alignments, resolve_refs)
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext
from bimforge.author.sweep import to_model
from bimforge.author.tests.test_emit_alignment import POB, PROFILE, RUN


def _file(tmp_path, name="ML"):
    p = tmp_path / "alignments.yaml"
    p.write_text(yaml.safe_dump({"alignments": {name: {
        "pob": POB, "run": RUN, "profile": PROFILE}}}), encoding="utf-8")
    return load_alignments(p)


def _ctx():
    return ProjectContext(name="Placement", schema="IFC4X3_ADD2", epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID(int=77))


def _headwall_like(tag="HW 1"):
    """A 10 x 3 x 6 ft 'stem' on a 10 x 8 x 1 ft 'footing', built at the
    origin in its own frame (x along the wall, y across it, z up)."""
    m = StructureModel("hw", _ctx())
    stem = Prism("stem", [(0, 2), (10, 2), (10, 5), (0, 5)], 1.0, 7.0)
    ftg = Prism("ftg", [(0, 0), (10, 0), (10, 8), (0, 8)], 0.0, 1.0)
    m.add(Element.from_geometry(f"{tag} stem", stem, ifc_class="IfcWall"))
    m.add(Element.from_geometry(f"{tag} footing", ftg, ifc_class="IfcFooting"))
    return m


def _world(el, p):
    th = math.radians(el.bearing_deg)
    c, s = math.cos(th), math.sin(th)
    return (c * p[0] - s * p[1] + el.x_ft, s * p[0] + c * p[1] + el.y_ft, p[2] + el.z_ft)


def test_the_file_is_read_once_and_shared(tmp_path):
    a = _file(tmp_path)
    assert load_alignments(tmp_path / "alignments.yaml") is a
    assert a["ML"].alignment.s_end == pytest.approx(1000 + 120 + 174.533 + 78.540)
    assert a["ML"].profile.elev(1050.0) == pytest.approx(240.0)


def test_refs_resolve_to_the_family_shapes(tmp_path):
    a = _file(tmp_path)
    p = resolve_refs({"alignment": {"ref": "ML"}, "profile": {"ref": "ML"},
                      "span_ft": 40}, a)
    assert p["alignment"]["name"] == "ML" and p["alignment"]["pob"] == POB
    assert p["profile"] == {"curves": PROFILE} and p["span_ft"] == 40
    with pytest.raises(ValueError, match="no alignment 'X'"):
        resolve_refs({"alignment": {"ref": "X"}}, a)


def test_an_item_lands_its_anchor_on_the_station_offset(tmp_path):
    a = _file(tmp_path)
    m = _headwall_like()
    rep = apply_placement(m, {"alignment": "ML", "items": [{
        "match": "^HW 1 ", "station": 1200.0, "offset": 30.0, "side": "Rt",
        "anchor": {"of": "^HW 1 stem$", "x": "mid", "y": "mid", "z": "max"},
        "elevation": 251.5, "x": "left", "y": "back"}]}, a)
    assert "2 elements on ML at 1200.00 30.00 Rt" in rep[0]
    al = a["ML"].alignment
    n, e = al.station_offset(1200.0, 30.0, "Rt")
    want = to_model(m.ctx, n, e, 251.5)
    stem, ftg = m.elements
    assert _world(stem, (5.0, 3.5, 7.0)) == pytest.approx(want, abs=1e-9)
    # local x runs LEFT and local y runs BACK (down-station)
    az = al.point_az(1200.0)[2]
    fwd = (math.sin(math.radians(az)), math.cos(math.radians(az)))
    x1 = _world(stem, (6.0, 3.5, 7.0))
    d = (x1[0] - want[0], x1[1] - want[1])
    assert d == pytest.approx((-fwd[1], fwd[0]), abs=1e-9)        # left
    y1 = _world(stem, (5.0, 4.5, 7.0))
    assert (y1[0] - want[0], y1[1] - want[1]) == pytest.approx((-fwd[0], -fwd[1]), abs=1e-9)
    # both elements moved together; geometry itself untouched
    assert (ftg.x_ft, ftg.y_ft, ftg.bearing_deg) == (stem.x_ft, stem.y_ft, stem.bearing_deg)
    assert {k: stem.placed_on[k] for k in ("alignment", "station", "offset", "side",
                                            "elevation")} == {
        "alignment": "ML", "station": 1200.0, "offset": 30.0, "side": "Rt",
        "elevation": 251.5}
    # the anchor in each element's own frame (the footing's frame is the stem's)
    assert stem.placed_on["anchor"] == pytest.approx((5.0, 3.5, 7.0))
    assert m.alignments and m.alignments[0][0] is al


def test_grade_skew_and_a_mirroring_frame(tmp_path):
    a = _file(tmp_path)
    m = _headwall_like()
    apply_placement(m, {"alignment": "ML", "items": [{
        "match": "^HW", "station": 1100.0, "anchor": [0, 0, 0], "grade": -4.0,
        "skew_deg": 30.0}]}, a)
    stem = m.elements[0]
    assert stem.z_ft + 200.0 == pytest.approx(a["ML"].profile.elev(1100.0) - 4.0)
    az = a["ML"].alignment.point_az(1100.0)[2]
    # default frame: x right, y ahead; a 30 deg skew turns it clockwise
    assert stem.bearing_deg == pytest.approx(-az - 30.0)
    with pytest.raises(ValueError, match="right-handed"):
        apply_placement(_headwall_like(), {"alignment": "ML", "items": [{
            "match": "^HW", "station": 1100.0, "elevation": 240.0,
            "x": "left", "y": "ahead"}]}, a)
    with pytest.raises(ValueError, match="places no element"):
        apply_placement(_headwall_like(), {"alignment": "ML", "items": [{
            "match": "^nothing", "station": 1100.0, "elevation": 240.0}]}, a)


def test_the_placed_ifc_agrees(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import numpy as np
    from bimforge.author.emit_ifc import emit_ifc
    a = _file(tmp_path)
    m = _headwall_like()
    apply_placement(m, {"alignment": "ML", "items": [{
        "match": "^HW 1 ", "station": 1200.0, "offset": 30.0, "side": "Lt",
        "anchor": {"of": "^HW 1 stem$", "z": "max"}, "elevation": 251.5,
        "x": "left", "y": "back"}]}, a)
    out = tmp_path / "hw.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    (stem,) = [e for e in f.by_type("IfcWall")]
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    v = np.array(ifcopenshell.geom.create_shape(s, stem).geometry.verts).reshape(-1, 3)
    k = m.ctx.ft_to_m
    n, e = a["ML"].alignment.station_offset(1200.0, 30.0, "Lt")
    want = np.array(to_model(m.ctx, n, e, 251.5)) * k
    top = v[np.isclose(v[:, 2], v[:, 2].max())]
    assert top.mean(axis=0) == pytest.approx(want, abs=1e-6)
    assert len(f.by_type("IfcAlignment")) == 1


def test_a_declared_line_is_held_to_the_shared_one(tmp_path):
    from bimforge.author.alignment import Alignment, Profile
    a = _file(tmp_path)
    m = StructureModel("x", _ctx())
    m.alignments.append((Alignment(POB, RUN, name="ML"), Profile(PROFILE)))
    assert adopt_shared(m, a) == []
    assert m.alignments[0][0] is a["ML"].alignment
    drift = dict(POB, easting=POB["easting"] + 0.05)
    m.alignments[:] = [(Alignment(drift, RUN, name="ML"), Profile(PROFILE))]
    (problem,) = adopt_shared(m, a)
    assert "off the shared one" in problem
    assert m.alignments[0][0] is not a["ML"].alignment


def test_federation_carries_one_alignment_per_line(tmp_path):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.federate import federate
    a = _file(tmp_path)
    paths = []
    for i, sta in enumerate((1100.0, 1250.0)):
        m = _headwall_like(f"HW {i + 1}")
        apply_placement(m, {"alignment": "ML", "items": [{
            "match": "^HW", "station": sta, "elevation": 240.0}]}, a)
        p = tmp_path / f"hw{i}.ifc"
        emit_ifc(m, str(p))
        paths.append((p, f"HW {i + 1}"))
    out = tmp_path / "fed.ifc"
    r = federate(paths, str(out), _ctx())
    f = ifcopenshell.open(str(out))
    assert [al.Name for al in f.by_type("IfcAlignment")] == ["ML"]
    assert r.alignments == 1
    assert len(f.by_type("IfcWall")) == 2


def _copy_example(tmp_path, stem):
    import shutil
    from pathlib import Path

    from bimforge.author.families import registry as reg
    ex = Path(reg.__file__).parent.parent / "examples"
    for name in (f"{stem}.spec.yaml", f"{stem}.paycodes.yaml"):
        shutil.copy(ex / name, tmp_path / name)
    p = tmp_path / f"{stem}.spec.yaml"
    return p, yaml.safe_load(p.read_text(encoding="utf-8"))


def test_est_bim_build_places_a_local_frame_family(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from bimforge.author.families import registry as reg
    _file(tmp_path)
    spec_path, doc = _copy_example(tmp_path, "demo-box")
    doc["project"]["alignments"] = "alignments.yaml"
    doc["placement"] = {"alignment": "ML", "items": [{
        "match": "^DB-", "station": 1100.0, "offset": 12.0, "side": "Lt",
        "anchor": [0, 0, 0], "grade": -6.0, "x": "ahead", "y": "left"}]}
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert reg.build_from_spec(spec_path) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "demo-box.ifc"))
    assert [a.Name for a in f.by_type("IfcAlignment")] == ["ML"]
    # DB-2 sits 20 ft AHEAD of DB-1 along the tangent (local x = ahead)
    import ifcopenshell.api
    import ifcopenshell.util.placement as up
    m = {e.Name: up.get_local_placement(e.ObjectPlacement)[:3, 3]
         for e in f.by_type("IfcFooting")}
    d = m["DB-2 demo footing"] - m["DB-1 demo footing"]
    k = 1200 / 3937
    assert math.hypot(d[0], d[1]) == pytest.approx(20.0 * k, abs=1e-9)
    # the build stationed the elements, with the authored anchors
    from bimforge.bim.linear_ref import read
    refs = {f.by_guid(g).Name: ps for g, ps in read(f).items()}
    assert refs["DB-1 demo footing"]["AnchorStationText"] == "11+00.00"
    assert refs["DB-2 demo footing"]["AnchorOffsetText"] == "12.00 Lt"
    assert refs["DB-2 demo footing"]["StationStartText"] == "11+18.00"   # 20 ft on, less 2


def test_est_bim_build_reads_a_line_native_familys_alignment_by_ref(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.families import registry as reg
    spec_path, doc = _copy_example(tmp_path, "bridge-standard")
    (tmp_path / "alignments.yaml").write_text(yaml.safe_dump({"alignments": {"BR": {
        "pob": doc["params"]["alignment"]["pob"], "run": doc["params"]["alignment"]["run"],
        "profile": doc["params"]["profile"]["curves"]}}}), encoding="utf-8")
    doc["project"]["alignments"] = "alignments.yaml"
    doc["params"]["alignment"] = {"ref": "BR"}
    doc["params"]["profile"] = {"ref": "BR"}
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert reg.build_from_spec(spec_path, check_only=True) == 0


def test_placement_needs_the_alignments_file(tmp_path):
    from bimforge.author.families import registry as reg
    spec_path, doc = _copy_example(tmp_path, "demo-box")
    doc["placement"] = {"alignment": "ML", "items": []}
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="placement: needs project.alignments"):
        reg.load_spec(spec_path)


def test_the_post_emit_check_reads_the_ifc_back(tmp_path):
    """ifc_alignment_problems: the IFC's line and a placed anchor against the
    model. Clean after emit; a moved element and a model line that is not the
    file's are caught."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api
    import ifcopenshell.util.placement as up
    from bimforge.author.alignment import Alignment
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.placement import ifc_alignment_problems
    a = _file(tmp_path)
    m = _headwall_like()
    apply_placement(m, {"alignment": "ML", "items": [{
        "match": "^HW 1 ", "station": 1250.0, "offset": 22.0, "side": "Lt",
        "anchor": {"of": "^HW 1 stem$", "z": "max"}, "elevation": 246.0,
        "x": "back", "y": "right"}]}, a)
    out = tmp_path / "hw.ifc"
    emit_ifc(m, str(out))
    assert ifc_alignment_problems(m, out) == []
    # the stem nudged 0.05 ft east in the FILE
    f = ifcopenshell.open(str(out))
    (stem,) = f.by_type("IfcWall")
    M = up.get_local_placement(stem.ObjectPlacement)
    M[0, 3] += 0.05 * m.ctx.ft_to_m
    ifcopenshell.api.run("geometry.edit_object_placement", f, product=stem,
                         matrix=M, is_si=True)
    moved = tmp_path / "moved.ifc"
    f.write(str(moved))
    (p,) = ifc_alignment_problems(m, moved)
    assert p.startswith("HW 1 stem: placed anchor in the IFC") and "offset" in p
    # a model whose line is not the file's
    drift = Alignment(dict(POB, easting=POB["easting"] + 0.02), RUN, name="ML")
    m.alignments[:] = [(drift, a["ML"].profile)]
    assert any("the IFC's line is" in q for q in ifc_alignment_problems(m, out))


def test_ties_are_a_pre_gate_check(tmp_path):
    from bimforge.author.placement import check_ties
    p = tmp_path / "alignments.yaml"
    al = _file(tmp_path)["ML"].alignment
    n, e = al.station_offset(1100.0, 10.0, "Rt")
    doc = {"alignments": {"ML": {"pob": POB, "run": RUN, "profile": PROFILE,
           "ties": [{"id": "A", "station": 1100.0, "offset": 10.0, "side": "Rt",
                     "northing": n + 0.25, "easting": e}],
           "profile_ties": [{"station": 1050.0, "elev": 240.0}]}}}
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    a = load_alignments(p)
    m = _headwall_like()
    assert check_ties(a)(m) == []                   # not built on the line yet
    apply_placement(m, {"alignment": "ML", "items": [{
        "match": "^HW", "station": 1100.0, "elevation": 240.0}]}, a)
    (prob,) = check_ties(a)(m)
    assert "tie A is 0.250 ft off the line (tol 0.1)" in prob
