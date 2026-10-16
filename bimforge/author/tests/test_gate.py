"""Gate: every built-in has a failing fixture; report-all; delete-on-fail."""
import uuid

import pytest

from bimforge.author.gate import (
    GateReport, check_arc_faceting, check_classification, check_lxw_volume,
    check_stated_quantities, delete_outputs, run_post, run_pre)
from bimforge.author.model import Element, StructureModel
from bimforge.author.paycodes import from_dict
from bimforge.author.primitives import ArcBand
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="f", guid_ns=uuid.UUID(int=1))

PC = from_dict({
    "rules": [{"match": "footing", "group": "g"}],
    "groups": {"g": {"measure": "GrossVolume"}},
    "codes": {"F": {"group": "g", "measure": "GrossVolume", "unit": "CY"}},
})


def _model(*els, **kw):
    m = StructureModel("fixture", CTX, **kw)
    for e in els:
        m.add(e)
    return m


def test_lxw_volume_failing_and_passing():
    good = Element("a", classifications=["F"], quantities={
        "count": 2, "length_ft": 4.0, "width_ft": 4.0, "height_ft": 2.0,
        "volume_cf": 64.0})
    bad = Element("b", classifications=["F"], quantities={
        "length_ft": 4.0, "width_ft": 4.0, "height_ft": 2.0, "volume_cf": 30.0})
    ref = Element("ref", quantities={"volume_cf": 1.0})   # unclassified: exempt
    fails = check_lxw_volume(_model(good, bad, ref))
    assert len(fails) == 1 and "b:" in fails[0]


def test_arc_faceting_failing_fixture():
    coarse = ArcBand("band", 0.375, 12.0, 24.0, 180.0, arc_segments=4)
    el = Element("saddle", geometry=coarse, classifications=["F"])
    fails = check_arc_faceting(_model(el))
    assert len(fails) == 1 and "faceting error" in fails[0]
    fine = ArcBand("band", 0.375, 12.0, 24.0, 180.0, arc_segments=64)
    assert check_arc_faceting(_model(Element("s", geometry=fine))) == []


def test_arc_faceting_checks_cf_pair():
    class BadSweep:
        volume_cf = 100.0
        faceted_volume_cf = 90.0          # 10% off - way past tolerance

        def body_solids(self):
            return []

    m = _model(Element.from_geometry("bad sweep", BadSweep(),
                                     classifications=[]))
    fails = check_arc_faceting(m)
    assert len(fails) == 1 and "faceting error" in fails[0]


def test_arc_faceting_skips_missing_cf_counterpart():
    class NoPair:
        volume_cf = 100.0                 # SectionPrism-style: no faceted twin

        def body_solids(self):
            return []

    m = _model(Element.from_geometry("plain", NoPair(), classifications=[]))
    assert check_arc_faceting(m) == []


def test_classification_check():
    el = Element("x footing", classifications=["GHOST"])
    fails = check_classification(_model(el), PC)
    assert any("GHOST" in f for f in fails)
    fails = check_classification(_model(Element("nothing classified")), PC)
    assert any("pays nothing" in f or "no element carries" in f for f in fails)
    assert check_classification(
        _model(Element("f", classifications=["F"])), PC) == []


def test_stated_quantities_check():
    m = _model(Element("a"))
    m.stated_quantities.append(("footing CY", 2.37, 2.3704, 5e-4))
    assert check_stated_quantities(m) == []
    m.stated_quantities.append(("rebar LBS", 100.0, 204.43, 0.01))
    fails = check_stated_quantities(m)
    assert len(fails) == 1 and "rebar LBS" in fails[0]


def test_stated_orientations_catches_a_mirror_that_quantities_cannot():
    """A MIRRORED swept section has identical area/volume, so every scalar in
    stated_quantities passes on a shape that is geometrically backwards — the
    #251 mirror-wedge escaped exactly this way. stated_orientations asserts a
    SIGNED handedness scalar keeps its expected sign; a mirror negates it, so
    this is the check none of the magnitude checks could be.

    Here the scalar is the top surface's slope direction (top at the +x edge
    minus top at the -x edge): +ve for a wedge that daylights to the west, and
    the family declares it must stay +ve. The mirrored build reports -2.0."""
    from bimforge.author.gate import check_stated_orientations
    m = _model(Element("wedge"))
    # Correct orientation: slope scalar +2, expected +1 -> passes.
    m.stated_orientations.append(("wedge slope", 2.0, +1, 1e-6))
    assert check_stated_orientations(m) == []
    # Mirrored build: same |slope| but negated -> flagged.
    m.stated_orientations.append(("mirrored wedge slope", -2.0, +1, 1e-6))
    fails = check_stated_orientations(m)
    assert len(fails) == 1 and "mirrored wedge slope" in fails[0]
    assert "sign" in fails[0].lower()


def test_stated_orientations_flags_a_degenerate_zero_scalar():
    """A handedness scalar within tolerance of zero is ambiguous — the section
    is neither clearly one hand nor the other — so it must fail loudly rather
    than silently satisfy either expected sign."""
    from bimforge.author.gate import check_stated_orientations
    m = _model(Element("flat"))
    m.stated_orientations.append(("degenerate", 0.0, +1, 1e-6))
    fails = check_stated_orientations(m)
    assert len(fails) == 1 and "degenerate" in fails[0]


def test_stated_orientations_runs_in_run_pre():
    """The orientation check is a pre-emit built-in: a mirrored section blocks
    every write, same as any other gate failure."""
    m = _model(Element("f", classifications=["F"]))
    m.stated_orientations.append(("mirror", -1.0, +1, 1e-6))
    rep = run_pre(m, PC)
    assert not rep.passed
    assert any("mirror" in f for f in rep.failures)


def test_run_pre_reports_all_failures_together_and_runs_model_checks():
    bad_el = Element("b footing", classifications=["F"], quantities={
        "length_ft": 4.0, "width_ft": 4.0, "height_ft": 2.0, "volume_cf": 30.0})
    m = _model(bad_el)
    m.stated_quantities.append(("x", 0.0, 1.0, 0.1))
    m.checks.append(lambda model: ["family check failed"])
    rep = run_pre(m, PC)
    assert not rep.passed
    joined = "\n".join(rep.failures)
    assert "reproduce GrossVolume" in joined
    assert "computed 0.0000" in joined
    assert "family check failed" in joined
    assert rep.checks_run >= 5
    assert "FAILED" in rep.format("pre")
    assert GateReport().passed


def test_delete_outputs(tmp_path):
    a = tmp_path / "m.ifc"
    a.write_text("x")
    delete_outputs({"ifc": str(a), "dxf": None,
                    "qto": str(tmp_path / "missing.xlsx")})
    assert not a.exists()


def test_run_post_contains_a_raising_check_and_still_deletes(tmp_path):
    """A post-check that RAISES (vs returning failures) must not bypass
    delete_outputs: the raise becomes a failure entry (exception context
    preserved) so the report fails and the outputs are removed."""
    out = tmp_path / "m.step"
    out.write_text("x")

    def exploding_check(model, outputs):
        raise RuntimeError("Face can only be created with closed wires")

    rep = run_post(_model(Element("a")), {"step": str(out)},
                   extra_checks=[exploding_check])
    assert not rep.passed
    assert not out.exists()                          # delete-on-fail held
    assert any("exploding_check raised" in f
               and "closed wires" in f for f in rep.failures)
    assert rep.checks_run == 1


def test_arc_faceting_message_omits_segments_for_sweeps():
    class BadSweep:
        volume_cf = 100.0
        faceted_volume_cf = 90.0

        def body_solids(self):
            return []

    m = _model(Element.from_geometry("swept", BadSweep(), classifications=[]))
    msg = check_arc_faceting(m)[0]
    assert "segments" not in msg          # a sweep has no arc_segments
    assert msg.endswith("exceeds 0.50%")
