"""author.families.bridge_standard: skew solver, spans, model assembly."""
import math

import pytest

from bimforge.author.alignment import Alignment
from bimforge.author.families.bridge_standard import bearing_line, spans

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
NORTH = [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 400.0}]


def test_bearing_line_unskewed_is_the_plan_normal():
    al = Alignment(POB, NORTH)
    (n, e), (dn, de) = bearing_line(al, 100.0, 0.0)
    assert (n, e) == (pytest.approx(100.0), pytest.approx(0.0))
    # heading north, unskewed bearing line runs east-west (the Lt normal)
    assert dn == pytest.approx(0.0, abs=1e-12)
    assert abs(de) == pytest.approx(1.0)


def test_bearing_line_skew_rotates_from_the_normal():
    al = Alignment(POB, NORTH)
    _p, (dn, de) = bearing_line(al, 100.0, 30.0)
    # 30 deg off the normal: the line leans 30 deg toward the alignment
    assert math.hypot(dn, de) == pytest.approx(1.0)
    assert abs(dn) == pytest.approx(math.sin(math.radians(30.0)), abs=1e-9)


def test_spans_are_consecutive_support_intervals():
    sup = [{"station": 100.0, "skew_deg": 20.0},
           {"station": 250.0, "skew_deg": 20.0},
           {"station": 380.0, "skew_deg": 0.0}]
    out = spans(sup)
    assert [(a["station"], b["station"]) for a, b in out] == [
        (100.0, 250.0), (250.0, 380.0)]


def test_spans_refuse_unordered_or_single_support():
    with pytest.raises(ValueError, match="ascending"):
        spans([{"station": 250.0, "skew_deg": 0.0},
               {"station": 100.0, "skew_deg": 0.0}])
    with pytest.raises(ValueError, match="two supports"):
        spans([{"station": 100.0, "skew_deg": 0.0}])


def test_deck_span_carries_length_and_volume_only():
    from bimforge.author.box_girder_section import BoxGirderSection
    from bimforge.author.families.bridge_standard import deck_span
    al = Alignment(POB, NORTH)
    sec = BoxGirderSection(deck_width=40.0, depth=6.0, overhang=4.0,
                           web_count=3, web_thickness=1.0, top_slab=0.75,
                           bot_slab=0.6)
    sw = deck_span("span 1", sec, al, 100.0, 250.0, 20.0, 20.0)
    assert sw.length_ft == pytest.approx(150.0)
    # parallel end skews: the corrections cancel, volume is area x run
    assert sw.volume_cf == pytest.approx(sec.area_sf * 150.0)
    assert sw.faceted_volume_cf == pytest.approx(sw.volume_cf, rel=1e-9)


def test_deck_span_opposed_skews_shift_volume_by_the_end_plane_rule():
    from bimforge.author.box_girder_section import BoxGirderSection
    from bimforge.author.families.bridge_standard import deck_span
    from bimforge.author.sweep import net_area_centroid
    al = Alignment(POB, NORTH)
    sec = BoxGirderSection(deck_width=40.0, depth=6.0, overhang=4.0,
                           web_count=3, web_thickness=1.0, top_slab=0.75,
                           bot_slab=0.6)
    a, xb, _zb = net_area_centroid(sec.outline, sec.voids)
    sw = deck_span("span 1", sec, al, 100.0, 250.0, 0.0, 30.0)
    want = a * 150.0 + a * xb * math.tan(math.radians(30.0))
    assert sw.volume_cf == pytest.approx(want)
    # a symmetric box has x_bar = 0, so the skew correction vanishes
    assert xb == pytest.approx(0.0, abs=1e-9)


class _ShiftedSection:
    """A BoxGirderSection translated in section-x, so x_bar != 0.

    The two tests above ride a symmetric box, where the end-plane term
    A*x_bar*tan(skew) is multiplied by ZERO: they pin the run term but
    say nothing about the correction. Sliding the same rings off the
    pivot makes the correction the ONLY thing separating the two skews.
    """

    def __init__(self, section, dx: float) -> None:
        self.depth, self.soffit_width = section.depth, section.soffit_width
        self.outline = [(x + dx, z) for x, z in section.outline]
        self.voids = [[(x + dx, z) for x, z in v] for v in section.voids]


def test_deck_span_end_plane_correction_bites_off_the_pivot():
    from bimforge.author.box_girder_section import BoxGirderSection
    from bimforge.author.families.bridge_standard import deck_span
    from bimforge.author.sweep import net_area_centroid
    al = Alignment(POB, NORTH)
    sec = _ShiftedSection(
        BoxGirderSection(deck_width=40.0, depth=6.0, overhang=4.0,
                         web_count=3, web_thickness=1.0, top_slab=0.75,
                         bot_slab=0.6), dx=5.0)
    a, xb, _zb = net_area_centroid(sec.outline, sec.voids)
    assert xb == pytest.approx(5.0, abs=1e-9)      # correction is now live
    ds, skew = 150.0, 30.0
    sq = deck_span("square", sec, al, 100.0, 250.0, 0.0, 0.0)
    sw = deck_span("skewed", sec, al, 100.0, 250.0, 0.0, skew)
    assert sq.volume_cf == pytest.approx(a * ds)
    want = a * ds + a * xb * math.tan(math.radians(skew))
    assert sw.volume_cf == pytest.approx(want)
    # and the correction is a real, sizeable shift - not a rounding wobble
    assert sw.volume_cf - sq.volume_cf == pytest.approx(
        a * 5.0 * math.tan(math.radians(30.0)))
    assert sw.faceted_volume_cf == pytest.approx(sw.volume_cf, rel=1e-9)


def _sec3():
    from bimforge.author.box_girder_section import BoxGirderSection
    return BoxGirderSection(deck_width=40.0, depth=6.0, overhang=4.0,
                            web_count=3, web_thickness=1.0, top_slab=0.75,
                            bot_slab=0.6)


def _flat_profile(elev=100.0):
    from bimforge.author.alignment import Profile
    return Profile([{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": 0.0,
                     "g_out_pct": 0.0, "length_ft": 1.0,
                     "evc_station": 1.0, "evc_elev": elev}])


def _plan_ring(element):
    """The world (n, e) base ring of a Prism-backed element.

    `Prism.body_solids()` keys the plan polygon "base" (a flat list of
    (n, e) points), not "plan"; asserting on it is asserting on the literal
    polygon the emitters extrude.
    """
    return element.geometry.body_solids()[0]["base"]


def test_soffit_elev_follows_profile_and_roll():
    from bimforge.author.families.bridge_standard import soffit_elev
    p = _flat_profile()
    # flat profile, no roll: the soffit sits `depth` below the deck pivot
    assert soffit_elev(p, None, None, 200.0, 0.0, 6.0) == pytest.approx(94.0)
    # under roll the section rotates as a rigid body about the pivot: a
    # point at plan offset x rides up by x*sin(phi) and the depth shortens
    # to depth*cos(phi)
    z = soffit_elev(p, [(0.0, 0.06), (400.0, 0.06)], None, 200.0, 10.0, 6.0)
    phi = math.atan(0.06)
    assert z == pytest.approx(100.0 + 10.0 * math.sin(phi)
                              - 6.0 * math.cos(phi))


def test_soffit_elev_includes_camber():
    from bimforge.author.families.bridge_standard import soffit_elev
    p = _flat_profile()
    plain = soffit_elev(p, None, None, 200.0, 0.0, 6.0)
    bowed = soffit_elev(p, None, [(0.0, 0.0), (200.0, 0.4), (400.0, 0.0)],
                        200.0, 0.0, 6.0)
    assert bowed - plain == pytest.approx(0.4)


def test_bent_columns_and_cap_are_placed_and_measured():
    from bimforge.author.families.bridge_standard import bent_elements
    al = Alignment(POB, NORTH)
    sup = {"station": 200.0, "skew_deg": 20.0, "type": "bent",
           "columns": {"count": 2, "dia": 4.0, "base_el": 70.0},
           "cap": {"width": 5.0, "depth": 4.0}}
    els = bent_elements("B1", sup, _sec3(), al, _flat_profile(), None, None)
    names = [e.name for e in els]
    assert sum("column" in n for n in names) == 2
    assert sum("cap" in n for n in names) == 1
    cap = [e for e in els if "cap" in e.name][0]
    # a rectangular cap declares the full L/W/H set, so the gate's
    # count x L x W x H == volume invariant actually checks it
    q = cap.quantities
    assert q["length_ft"] * q["width_ft"] * q["height_ft"] == pytest.approx(
        q["volume_cf"])
    assert q["height_ft"] == pytest.approx(4.0)
    assert q["width_ft"] == pytest.approx(5.0)
    col = [e for e in els if "column" in e.name][0]
    # cap soffit is deck soffit (94.0) minus the 4 ft cap depth
    assert col.quantities["height_ft"] == pytest.approx(90.0 - 70.0)
    assert col.quantities["volume_cf"] == pytest.approx(
        math.pi * 2.0 ** 2 * 20.0, rel=1e-9)      # exact-area circle


def test_bent_cap_runs_along_the_skewed_bearing_line():
    from bimforge.author.families.bridge_standard import (
        bearing_line, bent_elements)
    al = Alignment(POB, NORTH)
    sup = {"station": 200.0, "skew_deg": 30.0, "type": "bent",
           "columns": {"count": 2, "dia": 4.0, "base_el": 70.0},
           "cap": {"width": 5.0, "depth": 4.0}}
    els = bent_elements("B1", sup, _sec3(), al, _flat_profile(), None, None)
    cap = [e for e in els if "cap" in e.name][0]
    ring = _plan_ring(cap)
    # bearing_line speaks the SURVEY frame while the ring is in the MODEL
    # frame (x=east, y=north), so project through the same conversion the
    # family uses — sweep.to_model / to_model_dir (issue #156).
    from bimforge.author.sweep import to_model, to_model_dir
    (n0, e0), (dn, de) = bearing_line(al, 200.0, 30.0)
    x0, y0, _z = to_model(None, n0, e0)
    dx, dy = to_model_dir(dn, de)
    # the cap's long axis IS the bearing line: the plan ring's extent along
    # (dx, dy) is the cap length and its extent across is the cap width
    along = [(x - x0) * dx + (y - y0) * dy for x, y in ring]
    across = [-(x - x0) * dy + (y - y0) * dx for x, y in ring]
    assert max(along) - min(along) == pytest.approx(
        cap.quantities["length_ft"], rel=1e-6)
    assert max(across) - min(across) == pytest.approx(5.0, abs=1e-6)


def test_columns_sit_on_the_bearing_line_and_inside_the_cap():
    from bimforge.author.families.bridge_standard import (
        bearing_line, bent_elements)
    al = Alignment(POB, NORTH)
    sup = {"station": 200.0, "skew_deg": 30.0, "type": "bent",
           "columns": {"count": 3, "dia": 4.0, "base_el": 70.0},
           "cap": {"width": 5.0, "depth": 4.0}}
    els = bent_elements("B1", sup, _sec3(), al, _flat_profile(), None, None)
    cols = [e for e in els if "column" in e.name]
    cap_len = [e for e in els if "cap" in e.name][0].quantities["length_ft"]
    # survey -> model frame, as the family does (issue #156)
    from bimforge.author.sweep import to_model, to_model_dir
    (n0, e0), (dn, de) = bearing_line(al, 200.0, 30.0)
    x0, y0, _z = to_model(None, n0, e0)
    dx, dy = to_model_dir(dn, de)
    offs = []
    for c in cols:
        ring = _plan_ring(c)
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        offs.append(((cx - x0) * dx + (cy - y0) * dy,
                     abs((cx - x0) * -dy + (cy - y0) * dx)))
    for along, across in offs:
        assert across == pytest.approx(0.0, abs=1e-6)   # on the line
        assert abs(along) < cap_len / 2.0               # under the cap
    spaced = sorted(a for a, _ in offs)
    gaps = [b - a for a, b in zip(spaced, spaced[1:])]
    assert gaps == pytest.approx([gaps[0]] * len(gaps))  # evenly spaced


def test_abutment_elements_are_placed_and_measured():
    from bimforge.author.families.bridge_standard import abutment_elements
    al = Alignment(POB, NORTH)
    sup = {"station": 100.0, "skew_deg": 0.0, "type": "abutment",
           "stem": {"thickness": 3.0, "base_el": 80.0},
           "seat": {"width": 6.0, "bearing_depth": 0.5},
           "backwall": {"thickness": 1.0}}
    els = abutment_elements("A1", sup, _sec3(), al, _flat_profile(), None,
                            None)
    names = " ".join(e.name for e in els)
    assert "stem" in names and "backwall" in names
    for e in els:
        q = e.quantities
        assert q["volume_cf"] > 0.0
        assert q["length_ft"] * q["width_ft"] * q["height_ft"] == (
            pytest.approx(q["volume_cf"]))
    stem = [e for e in els if "stem" in e.name][0]
    # seat = deck soffit (94.0) - bearing depth; stem runs base -> seat
    assert stem.quantities["height_ft"] == pytest.approx(93.5 - 80.0)
    back = [e for e in els if "backwall" in e.name][0]
    assert back.quantities["height_ft"] == pytest.approx(94.0 - 93.5)


def test_substructure_refuses_impossible_elevations():
    from bimforge.author.families.bridge_standard import (
        abutment_elements, bent_elements)
    al = Alignment(POB, NORTH)
    high = {"station": 200.0, "skew_deg": 0.0, "type": "bent",
            "columns": {"count": 2, "dia": 4.0, "base_el": 99.0},
            "cap": {"width": 5.0, "depth": 4.0}}
    with pytest.raises(ValueError, match="base"):
        bent_elements("B1", high, _sec3(), al, _flat_profile(), None, None)
    sunk = {"station": 100.0, "skew_deg": 0.0, "type": "abutment",
            "stem": {"thickness": 3.0, "base_el": 99.0},
            "seat": {"width": 6.0, "bearing_depth": 0.5},
            "backwall": {"thickness": 1.0}}
    with pytest.raises(ValueError, match="base"):
        abutment_elements("A1", sunk, _sec3(), al, _flat_profile(), None,
                          None)


def _params():
    return {
        "alignment": {"pob": dict(POB), "run": list(NORTH)},
        "profile": {"curves": [
            {"bvc_station": 0.0, "bvc_elev": 130.0, "g_in_pct": 1.0,
             "g_out_pct": -1.0, "length_ft": 300.0,
             "evc_station": 300.0, "evc_elev": 130.0}]},
        "section": {"deck_width": 40.0, "depth": 6.0, "overhang": 4.0,
                    "webs": {"count": 3, "thickness": 1.0},
                    "top_slab": 0.75, "bot_slab": 0.6},
        "supports": [
            {"station": 60.0, "skew_deg": 0.0, "type": "abutment",
             "stem": {"thickness": 3.0, "base_el": 100.0},
             "seat": {"width": 6.0, "bearing_depth": 0.5},
             "backwall": {"thickness": 1.0}},
            {"station": 200.0, "skew_deg": 20.0, "type": "bent",
             "columns": {"count": 2, "dia": 4.0, "base_el": 100.0},
             "cap": {"width": 5.0, "depth": 4.0}},
            {"station": 340.0, "skew_deg": 0.0, "type": "abutment",
             "stem": {"thickness": 3.0, "base_el": 100.0},
             "seat": {"width": 6.0, "bearing_depth": 0.5},
             "backwall": {"thickness": 1.0}},
        ],
    }


def test_build_assembles_two_spans_and_three_supports():
    import uuid

    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="Fixture Bridge", guid_ns=uuid.UUID(int=7))
    m = build(_params(), ctx)
    names = [e.name for e in m.elements]
    assert sum("span" in n for n in names) == 2
    assert sum("column" in n for n in names) == 2
    assert sum("bent cap" in n for n in names) == 1
    assert sum("abutment" in n for n in names) == 4      # 2 x (stem+backwall)
    # every swept span declares length + volume only
    for e in m.elements:
        if "span" in e.name:
            assert set(e.quantities) == {"length_ft", "volume_cf"}


def test_build_refuses_missing_params_and_bad_support_type():
    import uuid

    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=7))
    p = _params()
    del p["section"]
    with pytest.raises(ValueError, match="missing"):
        build(p, ctx)
    p = _params()
    p["supports"][1]["type"] = "trestle"
    with pytest.raises(ValueError, match="support type"):
        build(p, ctx)


def test_diaphragm_adds_volume_inside_the_cells():
    import uuid

    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=7))
    plain = build(_params(), ctx)
    p = _params()
    p["supports"][1]["diaphragm"] = {"thickness": 2.0}
    withd = build(p, ctx)
    base = sum(e.quantities.get("volume_cf", 0.0) for e in plain.elements)
    more = sum(e.quantities.get("volume_cf", 0.0) for e in withd.elements)
    assert more > base
    dia = [e for e in withd.elements if "diaphragm" in e.name]
    assert len(dia) == 2                       # one solid per cell
    # the cells were already deducted, so the diaphragms add exactly their
    # own solid volume - no double count
    added = sum(e.quantities["volume_cf"] for e in dia)
    assert more - base == pytest.approx(added)
    # and each equals its cell area x thickness (parallel end skews)
    from bimforge.author.alignment import poly_area
    for e, cell in zip(dia, _sec3().voids):
        assert e.quantities["volume_cf"] == pytest.approx(
            poly_area(cell) * 2.0)


def test_diaphragm_at_an_end_support_stays_inside_the_deck():
    """A diaphragm at the first/last support sits wholly inboard.

    Centring it on the bearing would hang half the block past the end of
    the structure, where there is no deck to sit in (and no cell already
    deducted), so the clamp shifts it inboard - same volume, legal place.
    """
    import uuid

    from bimforge.author.alignment import poly_area
    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=7))
    p = _params()
    p["supports"][0]["diaphragm"] = {"thickness": 2.0}
    p["supports"][-1]["diaphragm"] = {"thickness": 2.0}
    m = build(p, ctx)
    dia = [e for e in m.elements if "diaphragm" in e.name]
    assert len(dia) == 4                       # 2 cells x 2 end supports
    for e in dia:
        sw = e.geometry
        assert sw.s0 >= 60.0 - 1e-9 and sw.s1 <= 340.0 + 1e-9
        assert sw.length_ft == pytest.approx(2.0)
    a1 = [e for e in dia if e.name.startswith("A1")]
    a3 = [e for e in dia if e.name.startswith("A3")]
    assert [(e.geometry.s0, e.geometry.s1) for e in a1] == [(60.0, 62.0)] * 2
    assert [(e.geometry.s0, e.geometry.s1) for e in a3] == [(338.0, 340.0)] * 2
    for e, cell in zip(a1, _sec3().voids):
        assert e.quantities["volume_cf"] == pytest.approx(
            poly_area(cell) * 2.0)
    # the clamp can only shift a block that FITS; a thicker-than-the-bridge
    # diaphragm would hang out either end whichever way it slid
    p = _params()
    p["supports"][0]["diaphragm"] = {"thickness": 400.0}
    with pytest.raises(ValueError, match="exceeds the whole"):
        build(p, ctx)


def test_registry_exposes_the_family():
    from bimforge.author.families import bridge_standard
    from bimforge.author.families.registry import available, get
    assert "bridge-standard" in available()
    assert get("bridge-standard") is bridge_standard.build


def test_worked_example_builds_and_passes_the_gate():
    """The shipped CI fixture (spec 4.8) survives the pre-emit gate."""
    from pathlib import Path

    from bimforge.author.families.registry import build_from_spec
    spec = (Path(__file__).resolve().parents[1] / "examples"
            / "bridge-standard.spec.yaml")
    assert spec.exists()
    rc = build_from_spec(spec, check_only=True)
    assert rc == 0


def test_unskewed_curved_span_declares_the_pappus_closed_form():
    """The shipped fixture puts a 20-deg bent mid-curve, which makes every
    one of its deck spans face-declared - so nothing there exercises the
    plumb Pappus path or the gate's closed-form-vs-facet pair. An unskewed
    span on the same geometry is what covers it."""
    from bimforge.author.box_girder_section import BoxGirderSection
    from bimforge.author.families.bridge_standard import deck_span
    from bimforge.author.primitives import FACET_TOLERANCE
    curve_len = math.pi * 800.0 * 30.0 / 180.0
    al = Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
        {"kind": "curve", "delta": "30-0-0", "radius": 800.0, "turn": "R",
         "length": curve_len}])
    sec = BoxGirderSection(deck_width=40.0, depth=6.0, overhang=4.0,
                           web_count=3, web_thickness=1.0, top_slab=0.75,
                           bot_slab=0.6)
    sw = deck_span("span 1 superstructure", sec, al, 120.0, 400.0, 0.0, 0.0)
    assert not sw._face_declared              # plumb closed form is declared
    # a symmetric section has x_bar = 0, so Pappus reduces to area x run
    # even on the curve - and the faceted loft must sit inside the band
    assert sw.volume_cf == pytest.approx(sec.area_sf * 280.0)
    err = abs(sw.faceted_volume_cf - sw.volume_cf) / sw.volume_cf
    assert err <= FACET_TOLERANCE
    assert sw.faceted_volume_cf < sw.volume_cf     # chords inscribe the arc


# ---------------------------------------------------------------------------
# Model frame (issue #156). The family built every element at raw survey
# coordinates: the shipped example put all 11 elements ~2,009,887 m from the
# model origin (= its 6,594,000 ftUS base easting) with element placements at
# (0, 0, 0), AND with north/east transposed. Neither gate could see it —
# volume is translation-invariant and rotation-invariant — so `est-bim kml`
# was the only thing that noticed, and it blamed the wrong bug.
# ---------------------------------------------------------------------------

def _survey_ctx():
    import uuid

    from bimforge.author.project import ProjectContext
    return ProjectContext(
        name="Survey Bridge", epsg=2226, base_e=6_594_000.0,
        base_n=1_943_000.0, base_h=100.0, guid_ns=uuid.UUID(int=21))


def _survey_params():
    """`_params()` relocated onto its project base — the real-world case."""
    p = _params()
    p["alignment"]["pob"] = {"station": 0.0, "northing": 1_943_000.0,
                             "easting": 6_594_000.0}
    return p


def _model_bounds(model):
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for el in model.elements:
        geoms = (el.geometry if isinstance(el.geometry, (list, tuple))
                 else [el.geometry])
        for g in geoms:
            if not hasattr(g, "body_solids"):
                continue
            for d in g.body_solids():
                if d["kind"] == "mesh":
                    pts = list(d["verts"])
                elif d["kind"] == "prism":
                    pts = [(u, v, d.get("z_bot", 0.0)) for u, v in d["base"]]
                else:
                    continue
                for p in pts:
                    for i in range(3):
                        lo[i] = min(lo[i], p[i] + (el.x_ft, el.y_ft,
                                                   el.z_ft)[i])
                        hi[i] = max(hi[i], p[i] + (el.x_ft, el.y_ft,
                                                   el.z_ft)[i])
    return lo, hi


def test_survey_based_bridge_emits_local_geometry():
    """A bridge surveyed at State Plane coordinates emits near the model
    origin. The datum belongs in IfcMapConversion, not in every vertex."""
    from bimforge.author.families.bridge_standard import build
    m = build(_survey_params(), _survey_ctx())
    lo, hi = _model_bounds(m)
    for i, axis in enumerate("xyz"):
        assert abs(lo[i]) < 1_000.0 and abs(hi[i]) < 1_000.0, (
            f"{axis} spans {lo[i]:.1f}..{hi[i]:.1f} ft from the origin — "
            "survey coordinates are baked into the geometry")


def test_survey_base_only_translates_the_model():
    """Relocating the same bridge onto a survey base must MOVE it, not
    reshape it: identical extents, identical declared volumes."""
    import uuid

    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    at_origin = build(_params(), ProjectContext(
        name="o", guid_ns=uuid.UUID(int=22)))
    on_survey = build(_survey_params(), _survey_ctx())

    lo_a, hi_a = _model_bounds(at_origin)
    lo_b, hi_b = _model_bounds(on_survey)
    for i in range(2):                      # x, y extents unchanged
        assert (hi_a[i] - lo_a[i]) == pytest.approx(hi_b[i] - lo_b[i], abs=1e-6)
    va = {e.name: e.quantities.get("volume_cf") for e in at_origin.elements}
    vb = {e.name: e.quantities.get("volume_cf") for e in on_survey.elements}
    assert va.keys() == vb.keys()
    for name, want in va.items():
        if want:
            assert vb[name] == pytest.approx(want, rel=1e-9), name


def test_due_north_bridge_runs_along_model_y():
    """The transposition half: `_params()` runs due north, so the deck must
    be long in y (north) and narrow in x (east) — 40 ft deck, 280 ft run."""
    import uuid

    from bimforge.author.families.bridge_standard import build
    from bimforge.author.project import ProjectContext
    m = build(_params(), ProjectContext(name="o", guid_ns=uuid.UUID(int=23)))
    lo, hi = _model_bounds(m)
    assert (hi[1] - lo[1]) > 200.0, "the run should lie along y (north)"
    assert (hi[0] - lo[0]) < 100.0, "the deck width should lie along x (east)"


def test_abutment_elevation_error_quotes_the_authored_datum():
    """PR #157 review: elevations are localized for GEOMETRY, but the error a
    bad `base_el` produces must still quote the ABSOLUTE elevations the spec
    was written in — telling an estimator their base is at 5 ft when they
    typed 99.0 sends them hunting the wrong thing. `bent_elements` already
    validated in absolute; `abutment_elements` did not."""
    import uuid

    from bimforge.author.families.bridge_standard import abutment_elements
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="datum", guid_ns=uuid.UUID(int=41), base_h=94.0)
    al = Alignment(POB, NORTH)
    sunk = {"station": 100.0, "skew_deg": 0.0, "type": "abutment",
            "stem": {"thickness": 3.0, "base_el": 99.0},
            "seat": {"width": 6.0, "bearing_depth": 0.5},
            "backwall": {"thickness": 1.0}}
    with pytest.raises(ValueError) as exc:
        abutment_elements("A1", sunk, _sec3(), al, _flat_profile(), None,
                          None, origin=ctx)
    msg = str(exc.value)
    assert "99" in msg, f"absolute base_el 99.0 not quoted: {msg}"
    assert " 5 " not in msg, f"localized elevation leaked into: {msg}"
