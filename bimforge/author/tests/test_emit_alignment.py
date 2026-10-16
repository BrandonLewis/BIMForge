"""The swept-along alignment as an IFC4X3 IfcAlignment (#332).

The curve must lie exactly under the geometry swept from the same Alignment:
the checks below sample bimforge's own alignment/profile and measure the
distance to the IFC curve ifcopenshell builds from the emitted layouts.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.geom  # noqa: E402
import ifcopenshell.validate  # noqa: E402
import numpy as np  # noqa: E402

from bimforge.author import gate  # noqa: E402
from bimforge.author.alignment import Alignment, Profile  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.author.sweep import SweptSection, to_model  # noqa: E402

POB = {"station": 1000.0, "northing": 1_943_100.0, "easting": 6_594_050.0}
RUN = [{"kind": "tangent", "bearing": "N 10-0-0 E", "length": 120.0},
       {"kind": "curve", "delta": "25-0-0", "radius": 400.0, "turn": "R",
        "length": 174.533},
       {"kind": "curve", "delta": "15-0-0", "radius": 300.0, "turn": "L",
        "length": 78.540}]
PROFILE = [{"bvc_station": 1050.0, "bvc_elev": 240.0, "g_in_pct": 3.0,
            "g_out_pct": -2.0, "length_ft": 200.0, "evc_station": 1250.0,
            "evc_elev": 240.0 + 0.03 * 200.0 - 0.05 / 400.0 * 200.0 ** 2}]
RECT = [(-6.0, -3.0), (6.0, -3.0), (6.0, 0.0), (-6.0, 0.0)]


def _model(schema="IFC4X3_ADD2", profile=True):
    ctx = ProjectContext(name="Alignment Fixture", schema=schema, epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=332))
    al = Alignment(POB, RUN, name="ML")
    prof = Profile(PROFILE) if profile else None
    sw = SweptSection("deck", RECT, al, 1010.0, 1360.0, profile=prof,
                      origin=ctx)
    m = StructureModel("align", ctx)
    m.add(Element.from_geometry("deck", sw, ifc_class="IfcSlab",
                                quantities={"volume_cf": sw.volume_cf}))
    return m, al, prof


def _emit(tmp_path, m, name="a.ifc"):
    out = tmp_path / name
    emit_ifc(m, str(out))
    return out, ifcopenshell.open(str(out))


def _worst_offset_m(f, m, al, prof, curve):
    st = ifcopenshell.geom.settings()
    sh = ifcopenshell.geom.create_shape(st, curve)
    v = np.array(sh.verts).reshape(-1, 3)
    e = np.array(sh.edges).reshape(-1, 2)
    a, b = v[e[:, 0]], v[e[:, 1]]
    ab = b - a
    k = m.ctx.ft_to_m
    worst = 0.0
    for s in np.linspace(al.s_start, al.s_end, 151):
        n, east, _az = al.point_az(s)
        z = prof.elev(s) if prof else 0.0
        p = np.array(to_model(m.ctx, n, east, z)) * k
        if prof is None:
            p, pa, pab = p[:2], a[:, :2], ab[:, :2]
        else:
            pa, pab = a, ab
        t = np.clip(((p - pa) * pab).sum(1) / (pab * pab).sum(1), 0.0, 1.0)
        worst = max(worst, np.linalg.norm(pa + pab * t[:, None] - p,
                                          axis=1).min())
    return worst


def test_the_gradient_curve_lies_on_the_swept_alignment(tmp_path):
    m, al, prof = _model()
    out, f = _emit(tmp_path, m)
    (ifc_al,) = f.by_type("IfcAlignment")
    assert ifc_al.Name == "ML"
    segs = [s.DesignParameters for s in f.by_type("IfcAlignmentSegment")
            if s.DesignParameters.is_a("IfcAlignmentHorizontalSegment")]
    # ifcopenshell closes each layout with a zero-length segment
    kinds = [s.PredefinedType for s in segs if s.SegmentLength > 0]
    assert kinds == ["LINE", "CIRCULARARC", "CIRCULARARC"]
    radii = [s.StartRadiusOfCurvature for s in segs if s.SegmentLength > 0]
    k = m.ctx.ft_to_m
    # IFC turns counter-clockwise for a POSITIVE radius: R turn < 0, L > 0
    assert radii[1] == pytest.approx(-400.0 * k)
    assert radii[2] == pytest.approx(300.0 * k)
    (curve,) = f.by_type("IfcGradientCurve")
    assert _worst_offset_m(f, m, al, prof, curve) < 1e-3     # chord sag only


def test_without_a_profile_the_plan_curve_is_written(tmp_path):
    m, al, _ = _model(profile=False)
    _out, f = _emit(tmp_path, m)
    assert not f.by_type("IfcGradientCurve")
    (curve,) = f.by_type("IfcCompositeCurve")
    assert _worst_offset_m(f, m, al, None, curve) < 1e-3


def test_alignment_passes_the_gate_and_validates(tmp_path):
    m, *_ = _model()
    out, f = _emit(tmp_path, m)
    assert gate._products_reach_site(f) == []
    assert gate._ifc_representation_type_check(m, out) == []
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg)
    assert lg.statements == []
    # one Model context, with the Axis subcontext under it
    roots = [c for c in f.by_type("IfcGeometricRepresentationContext")
             if not c.is_a("IfcGeometricRepresentationSubContext")
             and c.ContextType == "Model"]
    assert len(roots) == 1
    (ifc_al,) = f.by_type("IfcAlignment")
    refs = [r.RelatingStructure for r in ifc_al.ReferencedInStructures]
    assert [r.is_a() for r in refs] == ["IfcSite"]


def test_alignment_emission_is_byte_deterministic(tmp_path):
    a, _ = _emit(tmp_path, _model()[0], "one.ifc")
    b, _ = _emit(tmp_path, _model()[0], "two.ifc")
    assert a.read_bytes() == b.read_bytes()


def test_ifc4_opt_out_writes_no_alignment_and_says_so(tmp_path, capsys):
    m, *_ = _model(schema="IFC4")
    _out, f = _emit(tmp_path, m)
    assert f.schema == "IFC4"                 # which has no IfcAlignment at all
    assert "IfcAlignment is IFC4X3-only" in capsys.readouterr().err
