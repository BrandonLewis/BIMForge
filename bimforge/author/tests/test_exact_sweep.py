"""Exact alignment sweeps: IfcSectionedSolidHorizontal on the IfcAlignment
curve (#332), and the post-gate check that stands in for the volume check
ifcopenshell 0.9 cannot give that entity (IfcOpenShell#9820).

The tampering tests prove each leg of the check sees what it is for: a
mirrored section (vertex residual), a dropped void (wall area) and an
inflated declared volume. The shape tests hold the exact sweep to every
form of Element.geometry: a raw dict, a wrapper, a list of sweeps — and a
subclass that reshapes the section, which must be written as its mesh.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author import gate  # noqa: E402
from bimforge.author.alignment import Alignment, Profile  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import MirrorX, exact_of  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.author.sweep import SweptSection  # noqa: E402

POB = {"station": 1000.0, "northing": 1_943_100.0, "easting": 6_594_050.0}
RUN = [{"kind": "tangent", "bearing": "N 10-0-0 E", "length": 120.0},
       {"kind": "curve", "delta": "25-0-0", "radius": 400.0, "turn": "R",
        "length": 174.533},
       {"kind": "curve", "delta": "15-0-0", "radius": 300.0, "turn": "L",
        "length": 78.540}]
PROFILE = [{"bvc_station": 1050.0, "bvc_elev": 240.0, "g_in_pct": 3.0,
            "g_out_pct": -2.0, "length_ft": 200.0, "evc_station": 1250.0,
            "evc_elev": 240.0 + 6.0 - 0.05 / 400.0 * 200.0 ** 2}]
# asymmetric on purpose: a mirrored section must not look right
OUTER = [(-16.0, -6.0), (14.0, -6.0), (18.0, 0.0), (-18.0, 0.0)]
VOIDS = [[(-10.0, -5.0), (-2.0, -5.0), (-2.0, -1.0), (-10.0, -1.0)]]
ROLL = [(1000.0, -0.02), (1150.0, 0.06), (1400.0, 0.06)]
# small: camber is vertical here and along the pitched axis in the IFC, so it
# leans the section by its ordinate times the grade (SweptSection._lean_ft)
CAMBER = [(1000.0, 0.0), (1185.0, 0.1), (1400.0, 0.0)]


def _ctx(schema="IFC4X3_ADD2"):
    return ProjectContext(name="Exact Sweep Fixture", schema=schema,
                          epsg=2226, base_e=6_594_000.0, base_n=1_943_000.0,
                          base_h=200.0, guid_ns=uuid.UUID(int=3320))


def _sweep(ctx, cls=SweptSection, s0=1010.0, s1=1360.0, al=None, **kw):
    # the "normal" frame: square to the 3D tangent, the IFC default
    opts = dict(profile=Profile(PROFILE), roll=ROLL, camber=CAMBER,
                voids=VOIDS, origin=ctx, frame="normal")
    opts.update(kw)
    return cls("deck", OUTER, al or Alignment(POB, RUN, name="ML"), s0, s1,
               **opts)


def _model(schema="IFC4X3_ADD2", **kw):
    ctx = _ctx(schema)
    sw = _sweep(ctx, **kw)
    m = StructureModel("exact", ctx)
    m.add(Element.from_geometry("deck", sw, ifc_class="IfcSlab",
                                quantities={"volume_cf": sw.volume_cf}))
    return m, sw


def _model_of(geometry, volume_cf, schema="IFC4X3_ADD2"):
    m = StructureModel("exact", _ctx(schema))
    m.add(Element("deck", ifc_class="IfcSlab", classifications=[],
                  geometry=geometry, quantities={"volume_cf": volume_cf}))
    return m


def _emit(tmp_path, m):
    out = tmp_path / "x.ifc"
    emit_ifc(m, str(out))
    return out, ifcopenshell.open(str(out))


def _body(f):
    (p,) = f.by_type("IfcSlab")
    (rep,) = p.Representation.Representations
    return rep


def test_a_plumb_square_ended_sweep_is_one_sectioned_solid(tmp_path):
    m, sw = _model()
    assert sw.exact_reason is None
    out, f = _emit(tmp_path, m)
    rep = _body(f)
    (solid,) = rep.Items
    assert solid.is_a("IfcSectionedSolidHorizontal")
    assert rep.RepresentationType == "AdvancedSweptSolid"
    # on the alignment's own curve, one section per station, voids kept
    (curve,) = f.by_type("IfcGradientCurve")
    assert solid.Directrix == curve
    assert len(solid.CrossSections) == len(sw.ifc_sections())
    assert all(s.is_a("IfcArbitraryProfileDefWithVoids")
               for s in solid.CrossSections)
    assert not f.by_type("IfcFacetedBrep")
    rep_post = gate.run_post(m, {"ifc": str(out)})
    assert rep_post.passed, rep_post.failures


def test_the_drawn_sweep_lies_on_the_swept_surface(tmp_path):
    m, sw = _model()
    out, _f = _emit(tmp_path, m)
    assert gate._ifc_exact_sweep_check(m, out) == []
    assert gate._exact_sweep_names(out) == {"deck"}


def test_roll_is_sectioned_finely_enough_for_the_tolerance():
    _m, sw = _model()
    secs = sw.ifc_sections()
    from bimforge.author.primitives import profile_at
    phis = [profile_at(sw._phi, s["s"]) for s in secs]
    assert max(abs(b - a) for a, b in zip(phis, phis[1:])) <= \
        SweptSection.IFC_ROLL_STEP_RAD + 1e-12
    assert secs[0]["s"] == sw.s0 and secs[-1]["s"] == sw.s1


@pytest.mark.parametrize("kw, reason", [
    ({"end_skew": (0.0, 20.0)}, "skewed end"),
    # plumb, 6 ft deep on a 3% grade: the pitched IFC section leans ~2 in
    ({"frame": "plumb"}, "plumb sections on grade lean"),
    ({"camber": [(1000.0, 0.0), (1185.0, 0.4), (1400.0, 0.0)]},
     "normal sections on grade lean"),
])
def test_skewed_or_leaning_sweeps_stay_a_brep(tmp_path, kw, reason):
    m, sw = _model(**kw)
    assert sw.exact_reason.startswith(reason)
    assert "exact" not in sw.body_solids()[0]
    _out, f = _emit(tmp_path, m)
    rep = _body(f)
    assert rep.RepresentationType == "Brep"
    assert rep.Items[0].is_a("IfcFacetedBrep")


def test_ifc4_falls_back_to_the_mesh(tmp_path):
    m, _sw = _model(schema="IFC4")
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcFacetedBrep")
    assert gate._exact_sweep_names(out) == set()
    rep = gate.run_post(m, {"ifc": str(out)})
    assert rep.passed, rep.failures         # the volume check applies again


def test_a_transformed_sweep_degrades_to_its_mesh():
    _m, sw = _model()
    (d,) = MirrorX(sw).body_solids()
    assert d["kind"] == "mesh" and "exact" not in d


# ---------------------------------------------------------- tampering
def test_gate_catches_a_mirrored_section(tmp_path):
    m, _sw = _model()
    out, f = _emit(tmp_path, m)
    for pt in f.by_type("IfcCartesianPoint"):
        if len(pt.Coordinates) == 2 and any(
                pt in (c.OuterCurve.Points if hasattr(c, "OuterCurve") else ())
                for c in _body(f).Items[0].CrossSections):
            u, v = pt.Coordinates
            pt.Coordinates = (-u, v)
    f.write(str(out))
    fails = gate._ifc_exact_sweep_check(m, out)
    assert any("strays" in msg for msg in fails), fails


def test_gate_catches_a_dropped_void(tmp_path):
    m, _sw = _model()
    out, f = _emit(tmp_path, m)
    solid = _body(f).Items[0]
    solid.CrossSections = tuple(
        f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA",
                        OuterCurve=s.OuterCurve) for s in solid.CrossSections)
    f.write(str(out))
    fails = gate._ifc_exact_sweep_check(m, out)
    assert any("wall area" in msg for msg in fails), fails


def test_gate_catches_an_inflated_declared_volume(tmp_path):
    m, _sw = _model()
    out, _f = _emit(tmp_path, m)
    m.element("deck").quantities["volume_cf"] *= 1.02
    fails = gate._ifc_exact_sweep_check(m, out)
    assert any("declared volume" in msg for msg in fails), fails


# ------------------------------------------------- every geometry shape
def test_two_sweeps_on_one_element_are_each_exact_and_checked(tmp_path):
    ctx = _ctx()
    al, prof = Alignment(POB, RUN, name="ML"), Profile(PROFILE)
    a = _sweep(ctx, s0=1010.0, s1=1150.0, al=al, profile=prof)
    b = _sweep(ctx, s0=1200.0, s1=1360.0, al=al, profile=prof)
    m = _model_of([a, b], a.volume_cf + b.volume_cf)
    m.ctx = ctx
    out, f = _emit(tmp_path, m)
    items = _body(f).Items
    assert [i.is_a() for i in items] == ["IfcSectionedSolidHorizontal"] * 2
    assert len(f.by_type("IfcAlignment")) == 1      # one alignment, shared
    assert gate._ifc_exact_sweep_check(m, out) == []
    m.element("deck").quantities["volume_cf"] = a.volume_cf   # one forgotten
    fails = gate._ifc_exact_sweep_check(m, out)
    assert any("declared volume" in msg for msg in fails), fails


def test_a_raw_sectioned_dict_is_exact_too(tmp_path):
    _m, sw = _model()
    m = _model_of(sw.body_solids()[0], sw.volume_cf)
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcSectionedSolidHorizontal")
    assert gate.run_post(m, {"ifc": str(out)}).passed


class _PassThrough:
    """A wrapper that hands the sweep's dicts on untouched (and is no
    SweptSection): the solid is still exactly the sweep."""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def body_solids(self):
        return [dict(d) for d in self.inner.body_solids()]


def test_a_pass_through_wrapper_keeps_the_exact_sweep(tmp_path):
    _m, sw = _model()
    m = _model_of(_PassThrough(sw), sw.volume_cf)
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcSectionedSolidHorizontal")
    rep = gate.run_post(m, {"ifc": str(out)})
    assert rep.passed, rep.failures


def test_a_subclass_that_reshapes_the_section_is_written_as_its_mesh(tmp_path):
    ctx = _ctx()
    base = _sweep(ctx)

    class Tapered(SweptSection):
        # barrier-pilot's TaperedSweep idiom: reshape the section per station,
        # below the constant section ifc_sections() would write
        def _xf(self, s, ring, skew_tan=0.0):
            t = (s - self.s0) / (self.s1 - self.s0)
            return super()._xf(s, [(x * (1.0 + 0.2 * t), z) for x, z in ring],
                               skew_tan)

    sw = _sweep(ctx, cls=Tapered)
    (d,) = sw.body_solids()
    assert "exact" in d and exact_of(d) is None
    assert exact_of(base.body_solids()[0]) is not None
    m = _model_of(sw, sw.faceted_volume_cf)
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcFacetedBrep")
    rep = gate.run_post(m, {"ifc": str(out)})
    assert rep.passed, rep.failures         # the volume check applies again


def test_an_opening_host_keeps_its_sweep_as_a_mesh(tmp_path):
    from bimforge.author.primitives import Prism
    m, sw = _model()
    n, e, _az = sw.alignment.point_az(1200.0)
    from bimforge.author.sweep import to_model
    x, y, _z = to_model(m.ctx, n, e)
    hole = Prism("hole", [(x - 1, y - 1), (x + 1, y - 1), (x + 1, y + 1),
                          (x - 1, y + 1)], 0.0, 1000.0)
    m.openings.append(("deck", Element("hole", ifc_class="IfcOpeningElement",
                                       classifications=[], geometry=hole)))
    _out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcFacetedBrep")


def test_a_plumb_sweep_without_a_profile_is_exact(tmp_path):
    m, sw = _model(frame="plumb", profile=None, camber=None)
    assert sw.exact_reason is None          # a level directrix does not pitch
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcSectionedSolidHorizontal")
    rep = gate.run_post(m, {"ifc": str(out)})
    assert rep.passed, rep.failures


def test_gate_catches_a_plumb_sweep_drawn_pitched(tmp_path, monkeypatch):
    """The barrier-pilot 60MA barrier before exact_reason knew about grade: plumb
    sections, drawn square to the 3D tangent, lean their tops along the
    alignment though every vertex stays on the swept surface."""
    monkeypatch.setattr(SweptSection, "exact_reason", property(lambda s: None))
    m, _sw = _model(frame="plumb")
    out, f = _emit(tmp_path, m)
    assert _body(f).Items[0].is_a("IfcSectionedSolidHorizontal")
    fails = gate._ifc_exact_sweep_check(m, out)
    assert any("lean" in msg for msg in fails), fails
