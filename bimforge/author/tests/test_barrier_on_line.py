"""Barrier runs ON a project line (`on:`): swept along its tangents, arcs and
vertical profile, with the outboard face on the offset line."""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import pytest
import yaml

from bimforge.author.barrier_template import (offset_length,
                                              station_at_offset_length)
from bimforge.author.placement import load_alignments
from bimforge.author.sweep import to_model
from bimforge.author.tests.test_emit_alignment import POB, PROFILE, RUN

EX = Path(__file__).resolve().parents[1] / "examples"


def _alignments(tmp_path, ties=None):
    d = {"pob": POB, "run": RUN, "profile": PROFILE}
    if ties:
        d["ties"] = ties
    p = tmp_path / "alignments.yaml"
    p.write_text(yaml.safe_dump({"alignments": {"ML": d}}), encoding="utf-8")
    return load_alignments(p)


def _spec(tmp_path, on, ties=None):
    _alignments(tmp_path, ties)
    for n in ("concrete-barrier-842.spec.yaml", "concrete-barrier-842.paycodes.yaml"):
        shutil.copy(EX / n, tmp_path / n)
    p = tmp_path / "concrete-barrier-842.spec.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["params"] = {"alignment": {"ref": "ML"},
                     "runs": [{"name": "LT", "base_kind": "deck", "on": on,
                               "start_end": "approach", "end_end": "departure"}]}
    doc["project"].update(base=[6_594_000.0, 1_943_000.0, 200.0],
                          alignments="alignments.yaml", schema="IFC4X3_ADD2")
    doc["outputs"].pop("ifc_allow_local", None)
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def test_offset_length_is_exact_on_arcs(tmp_path):
    al = _alignments(tmp_path)["ML"].alignment
    # 120 ft tangent, 25 deg R 400 ft right, 15 deg R 300 ft left
    s_end = 1000 + 120 + 174.533 + 78.540
    o = 10.0                                            # 10 ft LEFT
    # right curve: the left side is OUTSIDE (longer), the left curve INSIDE
    want = 120 + (400 + 10) * math.radians(25) + (300 - 10) * math.radians(15)
    assert offset_length(al, 1000.0, s_end, o) == pytest.approx(want, abs=2e-3)
    s = station_at_offset_length(al, 1000.0, 150.0, o, s_end)
    assert offset_length(al, 1000.0, s, o) == pytest.approx(150.0, abs=1e-9)
    s = station_at_offset_length(al, s_end, 50.0, o, 1000.0)
    assert offset_length(al, s, s_end, o) == pytest.approx(50.0, abs=1e-9)


def test_an_842_runs_on_the_line(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import numpy as np
    from bimforge.author.families import registry as reg
    on = {"from_station": 1010.0, "to_station": 1360.0, "offset": 20.0,
          "side": "Lt", "grade": -0.5}
    spec = _spec(tmp_path, on)
    assert reg.build_from_spec(spec) == 0                   # every gate, pre and post
    f = ifcopenshell.open(str(tmp_path / "CAD" / "barrier-842.ifc"))
    assert [a.Name for a in f.by_type("IfcAlignment")] == ["ML"]
    walls = {w.Name: w for w in f.by_type("IfcWall")}
    assert set(walls) == {"LT 842 barrier run",          # the run's whole
                          "LT 842 barrier",
                          "LT 842 barrier end block (approach) [start]",
                          "LT 842 barrier end block (departure) [end]"}
    # the whole has no body; the barrier and its blocks are its parts
    assert walls["LT 842 barrier run"].Representation is None
    parts = {p.Name for r in walls["LT 842 barrier run"].IsDecomposedBy
             for p in r.RelatedObjects}
    assert {"LT 842 barrier",
            "LT 842 barrier end block (approach) [start]"} <= parts
    # plumb on a 3 % grade, the barrier leans off IFC's grade-pitched
    # sections by more than 2 mm: written as its mesh, not an exact sweep
    # (SweptSection.exact_reason); a level run is exact (below)
    run = walls["LT 842 barrier"]
    assert not any(i.is_a("IfcSectionedSolidHorizontal")
                   for r in run.Representation.Representations for i in r.Items)
    # its outboard face rides 20 ft Lt; its base the profile less 0.5 ft
    al = load_alignments(tmp_path / "alignments.yaml")["ML"]
    s = ifcopenshell.geom.settings()
    s.set(s.USE_WORLD_COORDS, True)
    v = np.array(ifcopenshell.geom.create_shape(s, run).geometry.verts).reshape(-1, 3)
    k = 1200.0 / 3937.0
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    st = AlignmentStationer(f, alignments(f)[0])
    d, off = st.locate_many(v[:, :2])
    # the 842's back face stands 1/4" in from the deck edge (x = 0): on the
    # tangent the face is exactly 20 - 0.0208 ft Lt; on the curves the mesh
    # is faceted (its chords sag inward by the gate's arc-step bound)
    tangent = st.station_at(d) / k < 1119.0
    assert off[tangent].max() / k == pytest.approx(20.0 - 0.25 / 12, abs=0.002)
    assert off.max() / k == pytest.approx(20.0, abs=0.2)
    # every vertex sits on or above the profile less 0.5 ft (the base), and
    # the base is reached all along - tangent, right curve and left curve
    sta = st.station_at(d) / k
    above = v[:, 2] / k + 200.0 - np.array([al.profile.elev(x) - 0.5 for x in sta])
    assert above.min() == pytest.approx(0.0, abs=0.01)
    on_base = sta[np.abs(above) < 0.01]
    for a, b in ((1020.0, 1120.0), (1120.0, 1294.5), (1294.5, 1350.0)):
        assert ((on_base > a) & (on_base < b)).any(), (a, b)
    # pay length along the outboard face: the three pieces sum to it
    import uuid
    from bimforge.author.families.registry import get
    from bimforge.author.placement import resolve_refs
    from bimforge.author.project import ProjectContext
    from bimforge.bim.linear_ref import read
    ctx = ProjectContext(name="x", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=5))
    m = get("concrete-barrier-842")(resolve_refs(
        {"alignment": {"ref": "ML"}, "runs": [{"name": "LT", "on": on}]},
        load_alignments(tmp_path / "alignments.yaml")), ctx)
    # (the run's whole is among the walls; it measures nothing)
    L = sum(m.element(n).quantities.get("length_ft", 0.0) for n in walls)
    want = offset_length(al.alignment, 1010.0, 1360.0, 20.0)
    assert L == pytest.approx(want, abs=0.01)
    assert abs(want - 350.0) > 1.0                  # it is not the station span
    assert read(f)[run.GlobalId]["OffsetText"].endswith("Lt")


def test_a_rt_barrier_and_a_bad_tie(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.families import registry as reg
    on = {"from_station": 1010.0, "to_station": 1110.0, "offset": 15.0,
          "side": "Rt", "elevation": 238.0}
    n, e = load_alignments(_alignments(tmp_path) and tmp_path / "alignments.yaml")[
        "ML"].alignment.station_offset(1050.0, 30.0, "Rt")
    good = [{"id": "T1", "station": 1050.0, "offset": 30.0, "side": "Rt",
             "northing": n + 0.03, "easting": e}]
    assert reg.build_from_spec(_spec(tmp_path, on, ties=good)) == 0
    import ifcopenshell
    f = ifcopenshell.open(str(tmp_path / "CAD" / "barrier-842.ifc"))
    (run,) = [w for w in f.by_type("IfcWall") if w.Name == "LT 842 barrier"]
    # level (no profile): the running barrier IS an exact sweep on the line
    assert any(i.is_a("IfcSectionedSolidHorizontal")
               for r in run.Representation.Representations for i in r.Items)
    from bimforge.bim.linear_ref import read
    ps = read(f)[run.GlobalId]
    # the 842 is 1'-9" at its base, its back face 1/4" in from x = 0
    assert ps["OffsetText"] == "13.25 Rt to 14.98 Rt"
    bad = [dict(good[0], northing=n + 0.4)]
    assert reg.build_from_spec(_spec(tmp_path, on, ties=bad), check_only=True) == 1


def test_on_runs_refuse_what_they_cannot_place(tmp_path):
    from bimforge.author.families.registry import get
    from bimforge.author.placement import resolve_refs
    from bimforge.author.project import ProjectContext
    import uuid
    als = _alignments(tmp_path)
    ctx = ProjectContext(name="x", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=5))
    build = get("concrete-barrier-842")

    def go(on):
        p = resolve_refs({"alignment": {"ref": "ML"},
                          "runs": [{"name": "X", "on": on}]}, als)
        return build(p, ctx)
    with pytest.raises(ValueError, match="not inside"):
        go({"from_station": 900.0, "to_station": 1100.0, "offset": 5, "grade": 0})
    with pytest.raises(ValueError, match="grade .* or elevation"):
        go({"from_station": 1010.0, "to_station": 1100.0, "offset": 5})
    with pytest.raises(ValueError, match="too short"):
        go({"from_station": 1010.0, "to_station": 1020.0, "offset": 5, "grade": 0})
    with pytest.raises(ValueError, match="needs params.alignment"):
        build({"runs": [{"name": "X", "on": {"from_station": 1, "to_station": 2,
                                              "offset": 0, "grade": 0}}]}, ctx)
