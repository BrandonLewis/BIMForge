"""STEP emitter: solids build, export, true-volume cross-check."""
import uuid

import pytest

pytest.importorskip("build123d")

from bimforge.author.emit_step import build_solids, emit_step, true_volume_check
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism, Tube
from bimforge.author.project import ProjectContext


def _model():
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=3))
    m = StructureModel("fixture", ctx)
    p = Prism("footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)], 0.0, z_top=2.0)
    m.add(Element.from_geometry("footing", p, ifc_class="IfcFooting"))
    return m


def _tube_model():
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=3))
    m = StructureModel("fixture", ctx)
    t = Tube("casing", 10.0, 1.0, 0.1)
    m.add(Element.from_geometry("casing", t, ifc_class="IfcPipeSegment"))
    return m


def test_tube_brep_builds_and_matches_analytic_annulus():
    """The annulus seam regression: one concatenated outer+inner polyline
    self-touches at angle 0 == 2pi and OCCT refuses the wire; the fix (outer
    face, inner hole) must still reproduce the analytic annulus volume."""
    m = _tube_model()
    (el, parts), = build_solids(m)
    import math
    exact = math.pi * (1.0 ** 2 - 0.9 ** 2) * 10.0
    got = sum(p.volume for p in parts)
    assert abs(got - exact) / exact < 0.005          # faceted at 64 segments
    assert true_volume_check(m, {}) == []


def test_nonconvex_barrier_cap_is_manifold_not_inside_out():
    """A _BarrierSolid whose section is re-entrant (the transcribed Type 836
    barrier) must ear-clip its end caps rather than fan them from vertex 0. A
    fan across a non-convex ring makes an inside-out, non-manifold shell whose
    STEP true volume comes back NEGATED (-200% off) — which the
    divergence-theorem face_volume check cannot see. (#253)"""
    from bimforge.author.culvert_headwall_wingwall import _BarrierSolid
    from bimforge.author.emit_step import _require_build123d, _solid_from_dict
    b3d = _require_build123d()
    # An L-shaped section (reflex corner at (1, 1)) swept straight along +Y.
    outline = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0),
               (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)]
    sections = [[(x, y, z) for (x, z) in outline] for y in (0.0, 5.0)]
    bs = _BarrierSolid("nb", sections)
    assert bs.volume_cf == pytest.approx((2 * 3 - 1 * 2) * 5.0, rel=1e-9)
    (d,) = bs.body_solids()
    got = sum(p.volume for p in _solid_from_dict(b3d, d))
    assert got > 0                                       # not inside-out
    assert abs(got - bs.volume_cf) / bs.volume_cf < 0.005


def test_hollow_prism_brep_subtracts_its_holes():
    """A Prism carrying inner void rings (a hollow HSS post, a mortar pocket)
    must have those holes punched in the STEP B-rep. Without it the solid reads
    high by the hole volume and true_volume_check deletes an otherwise-correct
    build. (#254)"""
    from bimforge.author.emit_step import _require_build123d, _solid_from_dict
    from bimforge.author.primitives import Prism
    b3d = _require_build123d()
    p = Prism("hollow", [(-2, -2.5), (2, -2.5), (2, 2.5), (-2, 2.5)], 0.0,
              z_top=3.0, holes=[[(-1, -1), (1, -1), (1, 1), (-1, 1)]])
    assert abs(p.volume_cf - 48.0) < 1e-9        # (4*5 - 2*2) * 3
    (d,) = p.body_solids()
    got = sum(part.volume for part in _solid_from_dict(b3d, d))
    assert abs(got - p.volume_cf) / p.volume_cf < 1e-6
    # end-to-end: the post-emit gate must not fail on the hollow prism
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=4))
    m = StructureModel("hollow-fixture", ctx)
    m.add(Element.from_geometry("post", p, ifc_class="IfcColumn"))
    assert true_volume_check(m, {}) == []


def test_prism_with_per_vertex_bottom_brep_matches_analytic():
    """A wedge Prism carrying a per-vertex `bottom_z` (sloping floor) has no
    uniform sweep depth, so the STEP path must build the triangulated B-rep —
    and its true OCCT volume must equal the analytic wedge. This is the shape
    the #251 retraction needed as ONE solid instead of a mirror-prone slab +
    wedge decomposition. (#251)"""
    from bimforge.author.emit_step import _require_build123d, _solid_from_dict
    from bimforge.author.primitives import Prism
    b3d = _require_build123d()
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    p = Prism("wedge", base, z_bot=0.0, z_top=4.0,
              bottom_z=[0.0, 2.0, 2.0, 0.0])            # depth 4 -> 2, mean 3
    assert p.volume_cf == pytest.approx(60.0)
    (d,) = p.body_solids()
    got = sum(part.volume for part in _solid_from_dict(b3d, d))
    assert abs(got - p.volume_cf) / p.volume_cf < 1e-6
    # end-to-end: the post-emit true-volume gate accepts the wedge
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=5))
    m = StructureModel("wedge-fixture", ctx)
    m.add(Element.from_geometry("wedge", p, ifc_class="IfcWall"))
    assert true_volume_check(m, {}) == []


def test_geometryless_none_sentinel_contributes_no_solid():
    """A quantity-only element declared geometry={"kind":"none"} (the historical
    sentinel some families/specs use in place of geometry=None) must emit no STEP
    solid rather than crash the kind dispatch, so a build carrying one keeps its
    outputs instead of true_volume_check deleting them. (#255)"""
    from bimforge.author.emit_step import _require_build123d, _solid_from_dict
    b3d = _require_build123d()
    assert _solid_from_dict(b3d, {"kind": "none"}) == []
    m = _model()
    m.add(Element("rebar", "IfcReinforcingBar", {"kind": "none"},
                  {"length_ft": 4.0, "weight_lb": 12.0}))
    solids = {el.name: parts for el, parts in build_solids(m)}
    assert solids["rebar"] == []                 # no solid from the sentinel
    assert true_volume_check(m, {}) == []        # and no spurious gate failure


def test_emit_step_writes_a_tube(tmp_path):
    out = tmp_path / "tube.step"
    msg = emit_step(_tube_model(), out)
    assert out.exists() and out.stat().st_size > 0
    assert "1 solids" in msg


def test_pierced_plate_brep_subtracts_the_bolt_holes():
    """A box solids dict with hole centres (index 6) must punch the holes,
    or the B-rep reads high by exactly the hole volume vs the Plate
    analytic (the lug/base-plate e2e regression)."""
    import math
    from bimforge.author.emit_step import _require_build123d, _solid_from_dict
    b3d = _require_build123d()
    d = {"kind": "box", "units": "in", "hole_dia": 1.3125, "segments": 64,
         "boxes": [(0.0, 0.0, 0.375, 12.0, 24.75, 0.75,
                    [(-3.0, -10.5), (3.0, -10.5), (-3.0, 10.5), (3.0, 10.5)])]}
    parts = _solid_from_dict(b3d, d)
    gross = 24.75 * 12.0 * 0.75
    holes = 4 * math.pi * (1.3125 / 2.0) ** 2 * 0.75
    want_cf = (gross - holes) / 1728.0
    got = sum(p.volume for p in parts)
    assert abs(got - want_cf) / want_cf < 0.005


def test_mesh_kind_brep_matches_analytic():
    """The R6 earthwork primitives emit "mesh" solids dicts (SectionPrism /
    BatteredWall); the STEP true-volume path must build them too, or every
    full build of a mesh-emitting family fails post-gate with outputs
    deleted wherever the [solids] extra is installed."""
    from bimforge.author.primitives import BatteredWall, SectionPrism
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=3))
    m = StructureModel("fixture", ctx)
    sp = SectionPrism("weir", profile=[(0, 0), (4, 0), (4, 2), (0, 2)],
                      length=10.0,
                      voids=[[(1, 0.5), (3, 0.5), (3, 1.5), (1, 1.5)]])
    m.add(Element.from_geometry("weir", sp, ifc_class="IfcWall"))
    bw = BatteredWall("wall", lol=[(0, 0), (10, 0), (10, 10)],
                      top_profile=[(0, 8), (10, 8)], key_index=0, base_el=0,
                      t_top=1.0, batter=1 / 12, side=+1)
    m.add(Element.from_geometry("wall", bw, ifc_class="IfcWall"))
    for el, parts in build_solids(m):
        want = el.quantities["volume_cf"]
        got = sum(p.volume for p in parts)
        assert got == pytest.approx(want, rel=1e-6), el.name
    assert true_volume_check(m, {}) == []


def test_build_solids_true_volume_matches_analytic():
    m = _model()
    (el, parts), = build_solids(m)
    assert sum(p.volume for p in parts) == pytest.approx(32.0, rel=1e-6)
    assert true_volume_check(m, {}) == []


def test_true_volume_check_catches_a_lie():
    m = _model()
    m.elements[0].quantities["volume_cf"] = 99.0     # model lies about itself
    fails = true_volume_check(m, {})
    assert len(fails) == 1 and "off analytic" in fails[0]


def test_emit_step_writes_a_file(tmp_path):
    out = tmp_path / "fixture.step"
    msg = emit_step(_model(), out)
    assert out.exists() and out.stat().st_size > 0
    assert "1 solids" in msg


def test_emit_step_is_byte_deterministic_across_processes(tmp_path):
    """Same regression class as emit_ifc/emit_dxf: OCCT's STEP writer stamps
    FILE_NAME's time_stamp with wall-clock time, which would otherwise make
    a rebuild of an unchanged model at a different moment byte-different.

    Two runs of `est-bim build` are two separate PROCESSES (never two calls
    in one process — OCCT's own NEXT_ASSEMBLY_USAGE_OCCURRENCE numbering is
    a per-process document counter, unrelated to model content, and calling
    emit_step twice in-process would spuriously vary on THAT instead)."""
    import subprocess
    import sys
    script = tmp_path / "_emit_once.py"
    script.write_text(
        "import sys\n"
        "from bimforge.author.emit_step import emit_step\n"
        "from bimforge.author.model import Element, StructureModel\n"
        "from bimforge.author.primitives import Prism\n"
        "from bimforge.author.project import ProjectContext\n"
        "import uuid\n"
        "ctx = ProjectContext(name='f', guid_ns=uuid.UUID(int=3))\n"
        "m = StructureModel('fixture', ctx)\n"
        "p = Prism('footing', [(-2, -2), (2, -2), (2, 2), (-2, 2)], 0.0, z_top=2.0)\n"
        "m.add(Element.from_geometry('footing', p, ifc_class='IfcFooting'))\n"
        "emit_step(m, sys.argv[1])\n",
        encoding="utf-8")
    a, b = tmp_path / "a.step", tmp_path / "b.step"
    for out in (a, b):
        subprocess.run([sys.executable, str(script), str(out)], check=True,
                        capture_output=True, text=True)
    ca, cb = a.read_bytes(), b.read_bytes()
    assert ca == cb
    from bimforge.author.emit_step import STEP_BUILD_STAMP
    assert STEP_BUILD_STAMP.encode() in ca


def test_friendly_error_without_build123d(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake(name, *a, **kw):
        if name == "build123d":
            raise ImportError(name)
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake)
    from bimforge.author.emit_step import _require_build123d
    with pytest.raises(RuntimeError, match=r"bimforge\[solids\]"):
        _require_build123d()
