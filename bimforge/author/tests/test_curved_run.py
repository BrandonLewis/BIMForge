import math
import pytest
from bimforge.author.alignment import parse_bearing
from bimforge.author.curved_run import _az_to_bearing
from bimforge.author.curved_run import alignment_from_path


@pytest.mark.parametrize("az", [0.0, 10.0, 45.0, 89.999, 90.0, 123.456,
                                180.0, 200.25, 270.0, 315.0, 359.99])
def test_az_to_bearing_round_trips_under_kink_tolerance(az):
    back = parse_bearing(_az_to_bearing(az)) % 360.0
    d = (back - az + 180.0) % 360.0 - 180.0
    assert abs(d) < 1e-7          # well under kink_check's 1e-6 deg


def _saf_path():
    # straight - arc(right 25 deg, R=300) - straight
    return [{"kind": "straight", "length": 20.0},
            {"kind": "arc", "radius": 300.0, "delta": 25.0, "turn": "R"},
            {"kind": "straight", "length": 20.0}]


def test_alignment_from_path_lengths_and_continuity():
    al = alignment_from_path(_saf_path())
    arc_len = 300.0 * math.radians(25.0)
    assert al.s_end == pytest.approx(20.0 + arc_len + 20.0)
    # tangent-continuous: no kinks anywhere inside the run
    assert al.kink_check(al.s_start, al.s_end) == []
    # curvature is 0 on the straights, 1/300 (right = negative) on the arc
    assert al.curvature(10.0) == pytest.approx(0.0)
    assert al.curvature(20.0 + arc_len / 2.0) == pytest.approx(-1.0 / 300.0)


def test_alignment_from_path_leading_arc_is_allowed():
    al = alignment_from_path(
        [{"kind": "arc", "radius": 100.0, "delta": 30.0, "turn": "L"},
         {"kind": "straight", "length": 10.0}])
    assert al.s_end == pytest.approx(100.0 * math.radians(30.0) + 10.0)


def test_alignment_from_path_rejects_bad_segments():
    with pytest.raises(ValueError, match="radius"):
        alignment_from_path([{"kind": "arc", "radius": -1.0, "delta": 5.0}])
    with pytest.raises(ValueError, match="delta"):
        alignment_from_path([{"kind": "arc", "radius": 50.0, "delta": 0.0}])
    with pytest.raises(ValueError, match="length"):
        alignment_from_path([{"kind": "straight", "length": 0.0}])
    with pytest.raises(ValueError, match="kind"):
        alignment_from_path([{"kind": "spiral", "length": 5.0}])


from bimforge.author.curved_run import build_running_prism

# a simple asymmetric 2-ft-wide, 3-ft-tall barrier-ish section (x from back
# face, +x toward traffic, z up) with an off-centre centroid so curvature
# changes the Pappus volume measurably.
_SECT = [(0.0, 0.0), (2.0, 0.0), (1.0, 3.0), (0.0, 3.0)]


def test_running_prism_length_and_volume_on_a_curve():
    al = alignment_from_path(_saf_path())
    el = build_running_prism("P 842 barrier", _SECT, al, al.s_start, al.s_end,
                             ifc="IfcWall", layer="S-CONC")
    assert el.quantities["length_ft"] == pytest.approx(al.s_end - al.s_start)
    assert el.quantities["volume_cf"] > 0.0
    assert el.ifc_class == "IfcWall"


def test_running_prism_left_vs_right_curve_differ_and_pass_the_gate():
    # +x (the section's offset direction) rides the alignment's left_normal,
    # which points to the OUTSIDE of a right/clockwise curve -> larger radius,
    # longer swept path -> MORE concrete than the mirror-image left curve. The
    # plumb SweptSection gate (closed form == faceted) must hold for both.
    arc_r = [{"kind": "straight", "length": 5.0},
             {"kind": "arc", "radius": 50.0, "delta": 40.0, "turn": "R"},
             {"kind": "straight", "length": 5.0}]
    arc_l = [{"kind": "straight", "length": 5.0},
             {"kind": "arc", "radius": 50.0, "delta": 40.0, "turn": "L"},
             {"kind": "straight", "length": 5.0}]
    vr = build_running_prism("R", _SECT, alignment_from_path(arc_r),
                             0.0, None, ifc="IfcWall", layer="S-CONC")
    vl = build_running_prism("L", _SECT, alignment_from_path(arc_l),
                             0.0, None, ifc="IfcWall", layer="S-CONC")
    assert vr.quantities["volume_cf"] != pytest.approx(vl.quantities["volume_cf"])
    # gate: the SweptSection under each Element agrees closed-form vs faceted
    for e in (vr, vl):
        sw = e.geometry
        assert sw.volume_cf == pytest.approx(sw.faceted_volume_cf, rel=1e-3)


from bimforge.author.curved_run import sweep_morph, _MorphSweep, _cap_tris
from bimforge.author.barrier_732sw_endblock import _EndBlockSolid


def _point_in_poly(p, poly):
    """Even-odd ray cast: is (x, z) strictly inside the 2-D ring `poly`?"""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < xc:
                inside = not inside
    return inside


def _lerp_ring(inboard, nose):
    def ring_at(u):   # u: 0 = inboard, 1 = nose
        return [(a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))
                for a, b in zip(inboard, nose)]
    return ring_at


def test_sweep_morph_straight_matches_the_straight_endblock_volume():
    # on a straight terminal (k=0) the morphing sweep volume must equal the
    # existing straight _EndBlockSolid loft between the same two rings.
    inboard = [(0.0, 0.0), (2.0, 0.0), (1.0, 3.0), (0.0, 3.0)]
    nose = [(0.0, 0.0), (1.0, 0.0), (1.0, 3.0), (0.0, 3.0)]
    L = 6.0
    al = alignment_from_path([{"kind": "straight", "length": L}])
    ring_at = _lerp_ring(inboard, nose)
    # station 0 = inboard end, station L = nose end -> u = s / L
    el = sweep_morph("blk", lambda s: ring_at(s / L), al, 0.0, L,
                     ifc="IfcWall", layer="S-CONC")
    straight = _EndBlockSolid("ref", inboard, nose, 0.0, L, "IfcWall",
                              "S-CONC", fan=True)
    assert el.quantities["volume_cf"] == pytest.approx(straight.volume_cf,
                                                       rel=1e-6)
    assert el.quantities["length_ft"] == pytest.approx(L)


def test_sweep_morph_straight_matches_endblock_for_a_non_convex_L_section():
    # the real 732sw/842 end-block profiles are L-shaped (non-convex). A
    # vertex-0 cap fan mis-integrates a non-convex ring; the morph volume must
    # still equal _EndBlockSolid (which ear_clips its caps) to 1e-6.
    inboard = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0),
               (1.0, 3.0), (0.0, 3.0)]                      # L, concave at (1,1)
    nose = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.5, 0.5),
            (0.5, 2.0), (0.0, 2.0)]                          # smaller L
    L = 6.0
    al = alignment_from_path([{"kind": "straight", "length": L}])
    ring_at = _lerp_ring(inboard, nose)
    el = sweep_morph("blk", lambda s: ring_at(s / L), al, 0.0, L,
                     ifc="IfcWall", layer="S-CONC")
    straight = _EndBlockSolid("ref", inboard, nose, 0.0, L, "IfcWall",
                              "S-CONC", fan=True)
    assert el.quantities["volume_cf"] == pytest.approx(straight.volume_cf,
                                                       rel=1e-6)


def test_sweep_morph_caps_are_valid_for_a_non_star_shaped_section():
    # A U-channel: vertex 0 (0,0) cannot see across the notch, so a naive
    # vertex-0 cap fan emits triangles that cross the cut-out (invalid mesh,
    # OCCT-rejectable). ear_clip caps must keep every cap triangle inside the
    # section. Volume cannot see this defect (fan area == shoelace area for any
    # simple poly), so assert it at the MESH level: each cap triangle's 2-D
    # centroid lies inside the section polygon.
    U = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (2.0, 3.0),
         (2.0, 1.0), (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)]
    L = 6.0
    al = alignment_from_path([{"kind": "straight", "length": L}])
    geom = _MorphSweep("u", lambda s: U, al, 0.0, L)
    ring2d = geom._rings2d[0]                       # CCW-wound (x, z) cap ring
    tris = _cap_tris(ring2d)
    assert len(tris) == len(ring2d) - 2            # a full fan-count triangulation
    for i0, i1, i2 in tris:
        cx = (ring2d[i0][0] + ring2d[i1][0] + ring2d[i2][0]) / 3.0
        cz = (ring2d[i0][1] + ring2d[i1][1] + ring2d[i2][1]) / 3.0
        assert _point_in_poly((cx, cz), ring2d), \
            f"cap triangle {(i0, i1, i2)} centroid ({cx}, {cz}) outside U"


def test_sweep_morph_on_an_arc_follows_the_curve_not_the_chord():
    # a constant section swept on an arc: a mid-station ring vertex must land on
    # the alignment (point_az), not on the straight chord between the ends.
    sect = [(0.0, 0.0), (1.0, 0.0), (0.0, 2.0)]
    al = alignment_from_path([{"kind": "arc", "radius": 40.0, "delta": 60.0,
                               "turn": "R"}])
    el = sweep_morph("arc", lambda s: sect, al, 0.0, al.s_end,
                     ifc="IfcWall", layer="S-CONC")
    solid = el.geometry.body_solids()[0]
    verts = solid["verts"]
    # the arc bulges off its chord by the sagitta R(1-cos(delta/2)) ~ 5.4 ft;
    # some emitted vertex must sit well off the straight chord end-to-end.
    # Derive the chord endpoints from the emitted verts themselves (min/max
    # model-y), so the whole check lives in ONE frame (the model frame).
    import math as _m
    ys = [v[1] for v in verts]
    p_lo = verts[ys.index(min(ys))]
    p_hi = verts[ys.index(max(ys))]
    x0, y0 = p_lo[0], p_lo[1]
    x1, y1 = p_hi[0], p_hi[1]
    def dist_to_chord(p):
        num = abs((y1 - y0) * p[0] - (x1 - x0) * p[1] + x1 * y0 - y1 * x0)
        return num / _m.hypot(x1 - x0, y1 - y0)
    assert max(dist_to_chord(v) for v in verts) > 1.0
    assert el.quantities["volume_cf"] > 0.0
    # oracle: a CONSTANT-section morph over the same alignment interval is the
    # same swept solid as build_running_prism (SweptSection / Pappus closed
    # form). The morph is FACETED (loft between per-station rings) while the
    # prism is closed-form, so they agree only to the faceting tolerance on a
    # coarse arc -- observed rel delta ~1.1e-3 (just over 1e-3), so 2e-2.
    ref = build_running_prism("ref", sect, al, 0.0, al.s_end,
                              ifc="IfcWall", layer="S-CONC")
    assert el.quantities["volume_cf"] == pytest.approx(
        ref.quantities["volume_cf"], rel=2e-2)


from bimforge.author.barrier_template import BarrierTemplate, build_barrier
from bimforge.author.barrier_section import BarrierSection
from bimforge.author.project import ProjectContext


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000149"})


def _mini_template():
    outline = [(0.0, 0.0), (2.0, 0.0), (1.0, 3.0), (0.0, 3.0)]

    def section_fn(run):
        return BarrierSection("m", "std", {"barriers": {"m": {
            "shape": "m", "variants": {"std": {"profile": outline}}}}})

    def rebar_fn(name, section, run, run_len):
        return []   # rebar coverage is exercised by the real families

    return BarrierTemplate(
        family_id="mini", label="mini", endblock_len_ft=6.0,
        section_fn=section_fn, rebar_fn=rebar_fn,
        endblock_fn=lambda *a, **k: [], default_run_name="M")


def test_path_run_emits_one_curved_running_prism_no_blocks():
    tmpl = _mini_template()
    path = _saf_path()
    m = build_barrier(tmpl, {"runs": [{"name": "NB", "path": path,
                     "start_end": "none", "end_end": "none"}]}, _ctx())
    prisms = [e for e in m.elements if e.name.endswith("mini barrier")]
    assert len(prisms) == 1
    total = 20.0 + 300.0 * math.radians(25.0) + 20.0
    assert prisms[0].quantities["length_ft"] == pytest.approx(total)
    assert prisms[0].quantities["volume_cf"] > 0.0


def test_path_and_straight_length_ft_together_is_an_error():
    tmpl = _mini_template()
    with pytest.raises(ValueError, match="both"):
        build_barrier(tmpl, {"runs": [{"name": "NB", "straight_length_ft": 50.0,
                      "path": _saf_path()}]}, _ctx())


def test_straight_only_path_is_an_error():
    tmpl = _mini_template()
    with pytest.raises(ValueError, match="straight_length_ft"):
        build_barrier(tmpl, {"runs": [{"name": "NB",
                      "path": [{"kind": "straight", "length": 30.0}],
                      "start_end": "none", "end_end": "none"}]}, _ctx())


def test_curved_run_emits_nonempty_ifc_and_dxf(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.emit_dxf import emit_dxf
    from bimforge.author.families import concrete_barrier_842 as fam

    run = {"name": "NB",
           "path": [{"kind": "straight", "length": 20.0},
                    {"kind": "arc", "radius": 300.0, "delta": 25.0, "turn": "R"},
                    {"kind": "straight", "length": 20.0}],
           "start_end": "approach", "end_end": "departure"}
    m = fam.build({"runs": [run]}, _ctx())
    ifc = tmp_path / "curved.ifc"
    dxf = tmp_path / "curved.dxf"
    # paycodes=None: a paymap is not needed to prove the geometry emits (mirrors
    # test_concrete_barrier_732sw.py::test_emit_nonempty_and_post_gate's form).
    emit_ifc(m, str(ifc), None, allow_local=True)
    emit_dxf(m, str(dxf))
    assert ifc.stat().st_size > 0 and dxf.stat().st_size > 0
    import ifcopenshell
    f = ifcopenshell.open(str(ifc))
    # the running prism AND both morphing end blocks emit as IfcWall -- if the
    # morphing loft did not survive OCCT there would be no wall body to emit.
    assert f.by_type("IfcWall")
