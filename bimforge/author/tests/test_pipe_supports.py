"""pipe-supports family: neutral params, quantities, gate checks, build."""
import uuid

import pytest

from bimforge.author.families import pipe_supports as ps
from bimforge.author.gate import run_pre
from bimforge.author.project import ProjectContext

#: NEUTRAL fixture — same schema as a bid's params, no client strings.
PARAMS = {
    "supports": [
        {"id": "PS-1", "station": 388.43, "pipe_invert_ft": 275.51},
        {"id": "PS-2", "station": 478.91, "pipe_invert_ft": 275.51},
    ],
    "span": {"clear_span_ft": 90.48},
    "footing": {"count": 2, "length_ft": 4.0, "width_ft": 4.0, "depth_ft": 2.0,
                "cover_in": 3.0, "max_wcm": 0.50},
    "grout": {"count": 2, "thickness_in": 1.5},
    "rebar": {"bar_size": 5, "lb_per_ft": 1.043, "spacing_in": 6.0,
              "bars_each_way": 7, "directions": 2, "mats": 2},
    "saddle": {
        "count": 2,
        "cl_approx_in": 20.5, "cl_approx_tolerance_in": 0.25,
        "saddle_plate": {"thickness_in": 0.375, "width_in": 12.0},
        "upper_strap": {"thickness_in": 0.375, "width_in": 12.0},
        "end_plate": {"thickness_in": 0.375, "width_in": 12.0,
                      "count_per_support": 2},
        "bearing_plate": {"thickness_in": 0.75, "height_in": 5.75,
                          "length_in": 12.0, "count_per_support": 1},
        "base_plate": {"thickness_in": 0.75, "length_in": 24.75,
                       "width_in": 12.0, "count_per_support": 1},
        "lug_plate": {"thickness_in": 0.375, "projection_in": 3.0,
                      "length_in": 12.0, "bolt_edge_distance_in": 1.5,
                      "count_per_support": 4},
        "collar_bolts": {"count": 4},
        "stiffener_plate": {"thickness_in": 0.375, "locations": 1,
                            "pieces_per_location": 2},
        "anchor_bolts": {"count": 4, "diameter_in": 0.75, "length_in": 18.0,
                         "min_embed_below_top_mat_in": 9.0,
                         "leveling_nuts": True},
        "holes": {"anchor_bolt_dia_in": 1.3125, "collar_bolt_dia_in": 0.8125},
    },
    "reference": {"casing": {"od_in": 24.0, "wall_in": 0.375},
                  "carrier": {"od_in": 9.05, "nominal_in": 8}},
    "assumptions": [
        {"key": "stiffener_half_width_in", "value": 12.0, "reason": "fixture"},
        {"key": "stiffener_x_offset_in", "value": 0.0, "reason": "fixture"},
        {"key": "saddle_wrap_deg", "value": 180, "reason": "fixture"},
        {"key": "collar_bolt_diameter_in", "value": 0.75, "reason": "fixture"},
        {"key": "collar_bolt_length_in", "value": 3.0, "reason": "fixture"},
        {"key": "collar_bolt_gauge_in", "value": 3.0, "reason": "fixture"},
        {"key": "anchor_bolt_projection_above_plate_in", "value": 1.25,
         "reason": "fixture"},
    ],
    "quantities": [
        {"item": "Support Footings", "qty": 2.3704, "unit": "CY"},
        {"item": "Support Rebar", "qty": 204.43, "unit": "LBS"},
        {"item": "Support Grout Pads", "qty": 0.5156, "unit": "CF"},
    ],
    "validation": {"groundwater_elevation_ft": [265, 267],
                   "min_freeboard_ft": 2.0, "arc_segments": 64,
                   "facet_tolerance": 0.005},
}

CTX = ProjectContext(name="Fixture Crossing", guid_ns=uuid.UUID(int=42))


def test_closed_forms_reproduce_hand_figures():
    assert ps.footing_cy(PARAMS) == pytest.approx(2.3704, abs=5e-4)
    assert ps.rebar_bar_length_ft(PARAMS) == pytest.approx(3.5)
    assert ps.rebar_bars_per_footing(PARAMS) == 28
    assert ps.rebar_lb(PARAMS) == pytest.approx(2 * 28 * 3.5 * 1.043, abs=1e-6)
    assert ps.grout_cf(PARAMS) == pytest.approx(
        2 * 24.75 * 12.0 * 1.5 / 1728.0, abs=1e-6)
    d = ps.plate_datums(PARAMS)
    assert d["cl"] == pytest.approx(1.5 + 0.75 + 5.75 + 12.375)   # 20.375
    assert abs(d["cl"] - 20.5) <= 0.25                            # sheet APPROX
    assert ps.casing_cl_ft(PARAMS, PARAMS["supports"][0]) == pytest.approx(
        275.51 + 9.05 / 24.0)


def test_build_produces_the_contractual_element_count():
    model = ps.build(PARAMS, CTX)
    # per support: 1 footing + 4 rebar + 1 grout + 7 steel + 2 bolts + 1 ref = 16
    assert len(model.elements) == 32
    assert len(model.assemblies) == 2
    names = [e.name for e in model.elements]
    assert "PS-1 pipe support footing" in names
    assert "PS-2 collar strap bolt" in names
    ref = model.element("PS-1 casing pipe (REFERENCE)")
    assert ref.classifications == []


def test_gate_passes_on_the_fixture_and_catches_regressions():
    model = ps.build(PARAMS, CTX)
    rep = run_pre(model)
    assert rep.passed, rep.format("pre")

    import copy
    bad = copy.deepcopy(PARAMS)
    bad["saddle"]["bearing_plate"]["height_in"] = 9.0     # springline drifts
    model = ps.build(bad, CTX)
    rep = run_pre(model)
    assert any("springline" in f for f in rep.failures)

    bad = copy.deepcopy(PARAMS)
    bad["footing"]["depth_ft"] = 1.0                      # embed minimum
    rep = run_pre(ps.build(bad, CTX))
    assert any("24 in minimum" in f for f in rep.failures)

    bad = copy.deepcopy(PARAMS)
    bad["assumptions"][0] = {"key": "stiffener_half_width_in", "value": 12.0,
                             "reason": ""}
    rep = run_pre(ps.build(bad, CTX))
    assert any("no documented reason" in f for f in rep.failures)

    bad = copy.deepcopy(PARAMS)
    bad["quantities"][0]["qty"] = 5.0                     # stated CY mismatch
    rep = run_pre(ps.build(bad, CTX))
    assert any("stated" in f for f in rep.failures)


def test_emit_pipeline_on_the_fixture(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_dxf import emit_dxf
    from bimforge.author.emit_ifc import emit_ifc
    model = ps.build(PARAMS, CTX)
    emit_ifc(model, str(tmp_path / "ps.ifc"), allow_local=True)
    emit_dxf(model, str(tmp_path / "ps.dxf"))
    import ifcopenshell
    f = ifcopenshell.open(str(tmp_path / "ps.ifc"))
    assert len(f.by_type("IfcElementAssembly")) == 2
    assert len(f.by_type("IfcMechanicalFastener")) == 4   # 2 supports x 2 groups
