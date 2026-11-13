"""bim.add_alignment: IfcAlignment added to a finished, georeferenced IFC4X3.

Fixtures are built in code: a bare IFC4X3 project with an IfcSite and an
IfcMapConversion (CRS in US survey feet, model in metres).
"""
from __future__ import annotations

import math

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402
import ifcopenshell.api.alignment as alapi  # noqa: E402
import yaml  # noqa: E402

from bimforge.author.alignment import M_PER_FT  # noqa: E402
from bimforge.bim.add_alignment import (  # noqa: E402
    AlignmentGateError, add_alignments, map_conversion, to_model)
from bimforge.bim.cli import main as cli_main  # noqa: E402

E0, N0 = 6_000_000.0, 2_000_000.0


def _model(schema="IFC4X3_ADD2", georef=True):
    f = ifcopenshell.api.run("project.create_file", version=schema)
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    metre = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[metre])
    ifcopenshell.api.run("context.add_context", f, context_type="Model")
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    if georef:
        ifcopenshell.api.run("georeference.add_georeferencing", f)
        ifcopenshell.api.run("georeference.edit_georeferencing", f,
                             projected_crs={"Name": "EPSG:2227"},
                             coordinate_operation={"Eastings": E0, "Northings": N0,
                                                   "OrthogonalHeight": 0.0,
                                                   "Scale": 1.0 / M_PER_FT})
    return f


def _tangent(bearing, length):
    return {"kind": "tangent", "bearing": bearing, "length": length}


POB = {"station": 1000.0, "northing": N0 + 100.0, "easting": E0 + 100.0}
#: all tangents: two angle points (N -> NE -> E)
ZIGZAG = {"name": "ZIGZAG", "pob": POB,
          "run": [_tangent("N 0-0-0 E", 200.0), _tangent("N 45-0-0 E", 100.0),
                  _tangent("N 90-0-0 E", 150.0)]}
#: tangent, 90-degree right curve, tangent
CURVED = {"name": "CURVED", "pob": POB,
          "run": [_tangent("N 0-0-0 E", 100.0),
                  {"kind": "curve", "delta": "90-0-0", "turn": "R", "radius": 200.0,
                   "length": math.pi * 200.0 / 2.0},
                  _tangent("N 90-0-0 E", 100.0)]}


def _h_segments(ifc_al):
    return [s.DesignParameters
            for s in alapi.get_layout_segments(alapi.get_horizontal_layout(ifc_al))]


def test_an_all_tangent_traverse_keeps_every_angle_point():
    f = _model()
    add_alignments(f, [ZIGZAG])
    (al,) = f.by_type("IfcAlignment")
    segs = _h_segments(al)
    lines = [s for s in segs if s.SegmentLength > 0]
    # three legs, not one chord from POB to end
    assert len(lines) == 3
    assert all(s.PredefinedType == "LINE" for s in lines)
    assert [round(s.SegmentLength / M_PER_FT, 6) for s in lines] == [200.0, 100.0, 150.0]
    mc = map_conversion(f)
    x, y = to_model(E0 + 100.0, N0 + 300.0, mc)       # the first angle point
    sx, sy = segs[1].StartPoint.Coordinates
    assert (sx, sy) == (pytest.approx(x), pytest.approx(y))


def test_a_curve_is_written_as_a_circular_arc_and_lands_on_the_site():
    f = _model()
    (rep,) = add_alignments(f, [CURVED])
    (al,) = f.by_type("IfcAlignment")
    kinds = [s.PredefinedType for s in _h_segments(al) if s.SegmentLength > 0]
    assert kinds == ["LINE", "CIRCULARARC", "LINE"]
    assert al.Decomposes[0].RelatingObject.is_a("IfcSite")
    assert rep["start"] == "10+00.00"
    names = sorted(r.Name for r in f.by_type("IfcReferent"))
    assert any("10+00.00" in n for n in names)


def test_extra_referents_are_added_in_feet():
    f = _model()
    add_alignments(f, [ZIGZAG], referents={"ZIGZAG": [1050.0, 1100.0]})
    names = {r.Name for r in f.by_type("IfcReferent")}
    assert {"10+50.00", "11+00.00"} <= names


def test_a_vertical_profile_is_written_and_gated():
    f = _model()
    end = 1000.0 + 450.0
    block = dict(ZIGZAG, profile={"pvis": [{"station": 1000.0, "elevation": 90.0},
                                           {"station": 1200.0, "elevation": 92.0},
                                           {"station": end, "elevation": 91.0}],
                                  "vc_length_ft": 0.0, "desc": "invert"})
    (rep,) = add_alignments(f, [block])
    assert rep["vertical"]
    (al,) = f.by_type("IfcAlignment")
    vl = alapi.get_vertical_layout(al)
    assert vl.Description == "invert"
    first = alapi.get_layout_segments(vl)[0].DesignParameters
    assert first.StartHeight * (1.0 / M_PER_FT) == pytest.approx(90.0)


def test_a_profile_that_does_not_span_the_horizontal_is_refused():
    f = _model()
    block = dict(ZIGZAG, profile={"pvis": [{"station": 1000.0, "elevation": 90.0},
                                           {"station": 1100.0, "elevation": 91.0}]})
    with pytest.raises(AlignmentGateError, match="must match exactly"):
        add_alignments(f, [block])


def test_a_rerun_never_stacks_a_second_alignment():
    f = _model()
    add_alignments(f, [ZIGZAG])
    with pytest.raises(AlignmentGateError, match="already holds"):
        add_alignments(f, [ZIGZAG])


def test_files_that_cannot_take_an_alignment_are_refused():
    with pytest.raises(AlignmentGateError, match="IFC4X3"):
        add_alignments(_model(schema="IFC4"), [ZIGZAG])
    with pytest.raises(AlignmentGateError, match="not georeferenced"):
        add_alignments(_model(georef=False), [ZIGZAG])


def test_cli_writes_on_a_pass_and_nothing_on_a_failure(tmp_path):
    ifc = tmp_path / "m.ifc"
    _model().write(str(ifc))
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump({"alignments": [CURVED]}), encoding="utf-8")
    out = tmp_path / "out.ifc"
    assert cli_main(["add-alignments", str(ifc), "--spec", str(spec),
                     "--path", "alignments", "--out", str(out)]) == 0
    assert len(ifcopenshell.open(str(out)).by_type("IfcAlignment")) == 1

    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"alignments": [dict(
        ZIGZAG, profile={"pvis": [{"station": 1000.0, "elevation": 1.0},
                                  {"station": 1001.0, "elevation": 1.0}]})]}),
        encoding="utf-8")
    before = ifc.read_bytes()
    assert cli_main(["add-alignments", str(ifc), "--spec", str(bad),
                     "--path", "alignments"]) == 1
    assert ifc.read_bytes() == before


def _seg_end(sp):
    """A horizontal segment's end point, evaluated from its own parameters."""
    x, y = sp.StartPoint.Coordinates
    d, L, r = sp.StartDirection, sp.SegmentLength, sp.StartRadiusOfCurvature
    if not r:
        return x + L * math.cos(d), y + L * math.sin(d)
    cx, cy = x - r * math.sin(d), y + r * math.cos(d)
    return cx + r * math.sin(d + L / r), cy - r * math.cos(d + L / r)


def _curve(radius, delta_deg, turn):
    return {"kind": "curve", "radius": radius, "delta": f"{delta_deg}-0-0",
            "turn": turn, "length": radius * math.radians(delta_deg)}


#: curve directly into curve, no tangent between: a curve split across two
#: sheets, a compound curve and a reverse curve (#52)
BACK_TO_BACK = {
    "split": [_curve(380.0, 46, "L"), _curve(380.0, 46, "L")],
    "compound": [_curve(339.0, 59, "R"), _curve(200.0, 29, "R")],
    "reverse": [_curve(400.0, 50, "L"), _curve(300.0, 50, "R")],
}


@pytest.mark.parametrize("kind", sorted(BACK_TO_BACK))
def test_back_to_back_curves_are_written_as_the_traverse(kind):
    """ifcopenshell's PI layout misplaces a curve that follows a curve with no
    tangent between (a 92-degree split curve came out as a 313-degree loop the
    other way, and the next segment started 55 m away; #52), and the gate's
    start and end check did not see it. Each segment must end where the next
    one starts and lie on the traverse."""
    from bimforge.author.alignment import Alignment
    run = [_tangent("N 0-0-0 E", 200.0)] + [dict(c) for c in BACK_TO_BACK[kind]]
    f = _model()
    add_alignments(f, [{"name": kind, "pob": POB, "run": run}])
    (al,) = f.by_type("IfcAlignment")
    segs = [s for s in _h_segments(al)]
    for a, b in zip(segs, segs[1:]):
        gap = math.dist(_seg_end(a), b.StartPoint.Coordinates) / M_PER_FT
        assert gap < 0.001, f"{a.PredefinedType} ends {gap:.3f} ft from the next start"
    A = Alignment(POB, run)
    mc = map_conversion(f)
    for seg, sp in zip(A.segments, segs):
        n, e, _az = A.point_az(seg["s1"])
        x, y = to_model(e, n, mc)
        assert math.dist(_seg_end(sp), (x, y)) / M_PER_FT < 0.001
