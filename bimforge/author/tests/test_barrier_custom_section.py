"""Per-run explicit section rings for the 842 / 732SW barrier families (#26):
a "Mod" barrier keeps its end blocks, rebar and validation."""
import math

import pytest

from bimforge.author.alignment import poly_area
from bimforge.author.barrier_custom import chamfer_top, plumb_nose
from bimforge.author.families import concrete_barrier_732sw as f732
from bimforge.author.families import concrete_barrier_842 as f842
from bimforge.author.project import ProjectContext
from bimforge.author.type_842_profile import type_842_profile

C = 1.0 / 12.0                           # B11-82's 1" chamfer

# Job C's 842 (Mod), "TYPE 842 SECTION WITH LIGHT PEDESTAL" in spirit: a
# 1'-2" top block over a stem stood 4" in, the top corners chamfered 1".
MOD = [(0.3333, 0.0), (1.75, 0.0), (1.2708, 2.9), (1.2708, 3.5 - C),
       (1.2708 - C, 3.5), (0.0208 + C, 3.5), (0.0208, 3.5 - C),
       (0.0208, 2.3333), (0.3333, 2.3333)]


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000026"})


def _run(**kw):
    return dict({"name": "NB", "straight_length_ft": 60.0}, **kw)


def _named(model, token):
    return [e for e in model.elements if token in e.name and e.geometry is not None]


def _volume(el):
    from bimforge.author.primitives import _signed_volume
    d = el.geometry.body_solids()[0]
    v = d["verts"]
    return _signed_volume([(v[a], v[b], v[c]) for a, b, c in d["tris"]])


@pytest.mark.parametrize("base_kind", ["deck", "wall", "trench"])
def test_the_derived_nose_is_section_g_g_for_the_standard_rings(base_kind):
    run = type_842_profile({}, base_kind=base_kind)
    assert plumb_nose(run) == pytest.approx(
        type_842_profile({}, base_kind=base_kind, face="vertical"))


def test_the_derived_nose_plumbs_a_mod_ring_and_keeps_its_vertex_count():
    nose = plumb_nose(MOD)
    assert len(nose) == len(MOD)
    front = 1.2708
    assert nose[1] == pytest.approx((front, 0.0))   # the toe pulls in
    assert nose[2] == pytest.approx((front, 2.9))   # so does the slope break
    assert nose[3:7] == pytest.approx(MOD[3:7])     # the chamfered top stays
    assert [x for x, _ in nose[7:]] + [nose[0][0]] == pytest.approx([0.0208] * 3)


def test_a_mod_842_keeps_its_end_blocks_rebar_and_volume():
    m = f842.build({"runs": [_run(profile=MOD)]}, _ctx())
    body = _named(m, "842 barrier")
    assert {e.name for e in body} == {
        "NB 842 barrier", "NB 842 barrier end block (approach) [start]",
        "NB 842 barrier end block (departure) [end]"}
    run_len = 60.0 - 2 * f842.ENDBLOCK_842_LEN
    prism = m.element("NB 842 barrier")
    assert _volume(prism) == pytest.approx(poly_area(MOD) * run_len, rel=1e-9)
    assert sum(e.quantities["length_ft"] for e in body) == pytest.approx(60.0)
    bars = [e for e in m.elements if e.ifc_class == "IfcReinforcingBar"]
    assert any("endblock-ap" in e.name for e in bars)
    vert = m.element("NB 842 reinforcing vert-face #5")
    std = f842.build({"runs": [_run()]}, _ctx()).element("NB 842 reinforcing vert-face #5")
    assert vert.quantities["count"] == std.quantities["count"]   # same run, same spacing


def test_an_explicit_nose_profile_wins():
    nose = [(0.0208, 0.0), (1.2708, 0.0), (1.2708, 2.9), (1.2708, 3.5 - C),
            (1.2708 - C, 3.5), (0.0208 + C, 3.5), (0.0208, 3.5 - C),
            (0.0208, 2.3333), (0.0208, 2.0)]
    inboard, got = f842._TEMPLATE.endblock_rings_fn(
        {"profile": MOD, "nose_profile": nose}, None, "approach")
    assert inboard == pytest.approx(MOD) and got == pytest.approx(nose)


def test_a_curved_run_morphs_between_the_custom_rings():
    inboard, nose = f842._TEMPLATE.endblock_rings_fn({"profile": MOD}, None, "departure")
    assert inboard == pytest.approx(MOD) and nose == pytest.approx(plumb_nose(MOD))


@pytest.mark.parametrize("bad, match", [
    ({"profile": [(0, 0), (1, 0)]}, "at least 3"),
    ({"profile": MOD, "nose_profile": list(reversed(plumb_nose(MOD)))}, "pair"),
    ({"profile": [(0, 0), (1, 0), (2, 0)]}, "no area"),
    ({"profile": [(0, 0), (1, 1), (1, 0), (0, 1)]}, "crosses itself"),
    ({"profile": MOD, "nose_profile": MOD[:-1]}, "pair"),
    ({"profile": MOD, "stem_h_ft": 3.0}, "stem_h_ft"),
    ({"profile": MOD, "chamfer_in": 1.0}, "chamfer_in"),
])
def test_rings_that_cannot_be_built_are_refused(bad, match):
    with pytest.raises(ValueError, match=match):
        f842.build({"runs": [_run(**bad)]}, _ctx())


def test_a_clockwise_ring_builds_the_same_barrier():
    vols = []
    for ring in (MOD, list(reversed(MOD))):
        m = f842.build({"runs": [_run(profile=ring)]}, _ctx())
        vols.append(sorted(abs(_volume(e)) for e in _named(m, "842 barrier")))
    assert vols[0] == pytest.approx(vols[1])
    assert plumb_nose(list(reversed(MOD))) == pytest.approx(
        list(reversed(plumb_nose(MOD))))


def test_a_nose_that_twists_through_the_loft_is_refused():
    # same count, but rotated one vertex: the loft would turn inside out
    nose = plumb_nose(MOD)
    with pytest.raises(ValueError, match="pair"):
        f842.build({"runs": [_run(profile=MOD, nose_profile=nose[3:] + nose[:3])]},
                   _ctx())


def test_chamfer_in_cuts_the_two_top_corners_of_the_standard_ring():
    plain = type_842_profile({})
    cut = type_842_profile({"chamfer_in": 1.0})
    assert len(cut) == len(plain) + 2
    # each corner loses a triangle of legs c: 1/2 c^2 sin(interior angle)
    (xb, zb), (xt, zt) = plain[1], plain[2]          # the sloping face
    slope = math.atan2(zt - zb, xb - xt)             # from the horizontal
    front = 0.5 * C * C * math.sin(slope)            # top meets slope at pi - slope
    back = 0.5 * C * C                               # square back corner
    assert poly_area(plain) - poly_area(cut) == pytest.approx(front + back, rel=1e-9)
    nose = type_842_profile({"chamfer_in": 1.0}, face="vertical")
    assert len(nose) == len(cut) and max(z for _, z in nose) == 3.5


def test_a_chamfered_842_builds_straight_with_its_end_blocks():
    m = f842.build({"runs": [_run(chamfer_in=1.0)]}, _ctx())
    assert len(_named(m, "end block")) == 2


def test_chamfer_top_refuses_a_chamfer_longer_than_its_edges():
    with pytest.raises(ValueError, match="chamfer"):
        chamfer_top([(0, 0), (1, 0), (1, 1), (0, 1)], 0.6)


def test_a_mod_732sw_needs_its_nose():
    ring = f732._TEMPLATE.section_fn({}).outline
    with pytest.raises(ValueError, match="nose_profile"):
        f732.build({"runs": [_run(profile=ring, handrail=False)]}, _ctx())
    m = f732.build({"runs": [_run(profile=ring, handrail=False,
                                  start_end="none", end_end="none")]}, _ctx())
    assert len(_named(m, "end block")) == 0


def test_a_mod_732sw_takes_a_nose_per_end_kind():
    row = f732._row_732({})
    from bimforge.author.barrier_732sw_endblock import nose_section
    ring = f732._TEMPLATE.section_fn({}).outline
    noses = {"approach": nose_section(row, approach=True),
             "departure": nose_section(row, approach=False)}
    custom = f732.build({"runs": [_run(profile=ring, nose_profile=noses,
                                       handrail=False)]}, _ctx())
    std = f732.build({"runs": [_run(handrail=False)]}, _ctx())
    for n in ("NB 732sw barrier end block (approach) [start]",
              "NB 732sw barrier end block (departure) [end]"):
        assert _volume(custom.element(n)) == pytest.approx(_volume(std.element(n)))


def test_the_templates_are_public():
    assert f842.template() is f842._TEMPLATE
    assert f732.template() is f732._TEMPLATE


def test_a_mod_842_on_the_line_passes_every_gate(tmp_path):
    pytest.importorskip("ifcopenshell")
    import yaml
    from bimforge.author.families import registry as reg
    from bimforge.author.tests.test_barrier_on_line import _spec
    p = _spec(tmp_path, {"from_station": 1010.0, "to_station": 1360.0,
                         "offset": 20.0, "side": "Lt", "grade": -0.5})
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["params"]["runs"][0]["profile"] = [list(v) for v in MOD]
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert reg.build_from_spec(p) == 0
