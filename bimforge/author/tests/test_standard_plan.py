"""standard-plan: slicing, table lookups, hand-computed volumes."""
import uuid

import pytest

from bimforge.author.families.standard_plan import build
from bimforge.author.gate import run_pre
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="f", guid_ns=uuid.UUID(int=7))

TABLES = {"type_1_case_1": {
    "stem_top_thickness_ft": 1.0,
    "table": {
        8: {"W_ft": 6.0, "C_ft": 2.0, "B_ft": 4.0, "F_ft": 1.0, "T_ft": 1.0,
            "batter": "NONE"},
        10: {"W_ft": 6.75, "C_ft": 2.25, "B_ft": 4.5, "F_ft": 1.0, "T_ft": 1.0,
             "batter": "NONE"},
    }}}

PARAMS = {
    "alignment": {"pob": {"station": 0.0, "northing": 0.0, "easting": 0.0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                           "length": 64.0}]},
    "tables": TABLES,
    "walls": [{
        "name": "R1", "wall_type": 1, "front_side": "Lt",
        "beg": {"station": 0.0}, "end": {"station": 64.0}, "grid_ft": 8.0,
        "design_h_segments": [{"length_ft": 32.0, "H_ft": 8},
                              {"length_ft": 32.0, "H_ft": 10}],
        "top_of_wall": {"start_station": 0.0, "grid_ft": 8.0,
                        "elevs": [109.0] * 9},
        "footing_bottom": {"steps": [{"station": 0.0, "elev": 100.0}]},
    }],
}


def test_slices_and_hand_computed_volumes():
    m = build(PARAMS, CTX)
    # 64 ft / 8 ft grid -> 8 slices x (footing + stem) = 16 elements
    assert len(m.elements) == 16
    # first 32 ft at H=8: stem top 109, ftg bottom 100, F=1 -> h = 8, T = 1
    stem = m.element("R1 retaining wall stem 0+00.00")
    assert stem.quantities["volume_cf"] == pytest.approx(8.0 * 1.0 * 8.0)
    foot = m.element("R1 retaining wall footing 0+00.00")
    assert foot.quantities["volume_cf"] == pytest.approx(8.0 * 6.0 * 1.0)
    # second half at H=10 uses the wider table row
    foot2 = m.element("R1 retaining wall footing 0+32.00")
    assert foot2.quantities["width_ft"] == 6.75
    assert run_pre(m).passed


def test_segment_sum_check_fires():
    import copy
    bad = copy.deepcopy(PARAMS)
    bad["walls"][0]["design_h_segments"][0]["length_ft"] = 10.0
    m = build(bad, CTX)
    rep = run_pre(m)
    assert any("segments sum" in f for f in rep.failures)


def test_missing_params():
    with pytest.raises(ValueError, match="missing"):
        build({"tables": {}}, CTX)


def test_b3_paycodes_classify_footing_and_stem():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-b3-retaining-wall.paycodes.yaml")
    pc = pc_mod.load(p)
    m = build(PARAMS, CTX)
    pc_mod.apply(m, pc)
    stem = m.element("R1 retaining wall stem 0+00.00")
    foot = m.element("R1 retaining wall footing 0+00.00")
    assert stem.classifications == ["STRUCT-CONC-RW"]
    assert foot.classifications == ["STRUCT-CONC-RW"]


TABLES6 = {"type_6a_case_1": {
    "stem_thickness_ft": 0.6354, "footing_thickness_ft": 1.0, "toe_ft": 0.6667,
    "table": {4.0: {"W_ft": 3.5}, 6.0: {"W_ft": 4.5}}}}

PARAMS6 = {
    "alignment": {"pob": {"station": 0.0, "northing": 0.0, "easting": 0.0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                           "length": 16.0}]},
    "tables": TABLES6,
    "walls": [{
        "name": "W6", "wall_type": "6a", "front_side": "Lt",
        "beg": {"station": 0.0}, "end": {"station": 16.0}, "grid_ft": 8.0,
        "design_h_segments": [{"length_ft": 16.0, "H_ft": 6}],
        "top_of_wall": {"start_station": 0.0, "grid_ft": 8.0,
                        "elevs": [107.0] * 3},
        "footing_bottom": {"steps": [{"station": 0.0, "elev": 100.0}]},
    }],
}


def test_type6a_short_wall_build_and_volumes():
    """A string wall_type ("6a") flows through the whole build: 8-in-increment
    design H, constant 7-5/8" stem, footing width from the W-only table."""
    m = build(PARAMS6, CTX)
    # 16 ft / 8 ft grid -> 2 slices x (footing + stem) = 4 elements
    assert len(m.elements) == 4
    # H=6: top 107, ftg bottom 100, F=1 -> stem h = 6, T = 0.6354
    stem = m.element("W6 retaining wall stem 0+00.00")
    assert stem.quantities["volume_cf"] == pytest.approx(8.0 * 0.6354 * 6.0)
    foot = m.element("W6 retaining wall footing 0+00.00")
    assert foot.quantities["volume_cf"] == pytest.approx(8.0 * 4.5 * 1.0)
    assert run_pre(m).passed


def test_b3_example_spec_builds_check_only():
    from pathlib import Path
    from bimforge.author.families.registry import build_from_spec
    spec = (Path(__file__).resolve().parents[1]
            / "examples" / "caltrans-b3-retaining-wall.spec.yaml")
    assert build_from_spec(spec, check_only=True) == 0


#: A project base off the origin, horizontally and vertically: the frame a
#: real job has, and the one the base-zero tests above cannot tell apart
#: from the survey frame.
CTX_BASE = ProjectContext(name="f", guid_ns=uuid.UUID(int=7),
                          base_e=6594000.0, base_n=1943000.0, base_h=100.0)


def _real_pob(params, n=1943000.0, e=6594000.0):
    import copy
    out = copy.deepcopy(params)
    out["alignment"]["pob"] = {"station": 0.0, "northing": n, "easting": e}
    return out


def _corners(el):
    return el.geometry.base


def test_elevations_are_model_z_relative_to_base_h():
    """A footing bottom at elevation 100 and a top of wall at 109 sit at
    model z 0 and 9 when the project base is at elevation 100 (the model
    frame is z = E - base_h, as every alignment family writes it)."""
    m = build(_real_pob(PARAMS), CTX_BASE)
    foot = m.element("R1 retaining wall footing 0+00.00")
    stem = m.element("R1 retaining wall stem 0+00.00")
    assert foot.geometry.z_bot == pytest.approx(0.0)
    assert foot.geometry.z_top == pytest.approx(1.0)
    assert stem.geometry.z_bot == pytest.approx(1.0)
    assert stem.geometry.z_top == pytest.approx(9.0)


def test_a_local_pob_with_a_real_base_is_refused_once():
    """The pob is survey (State Plane) coordinates, as the bridge's is: a
    {0, 0} pob under a real base would put the wall at the zone's origin, so
    the family says so once, before the gate's per-slice findings."""
    with pytest.raises(ValueError, match=r"(?s)alignment pob .*survey .*"
                       r"State Plane.*northing 1943000.*easting 6594000"):
        build(PARAMS, CTX_BASE)


def test_wall_runs_along_its_bearing_in_the_model_frame():
    """A wall on a N 0 E line runs along model +y (north), its plan local to
    the project base, and its Lt front face lies west (-x) of the line: plan
    points are (northing, easting) until to_model swaps them (#156)."""
    m = build(_real_pob(PARAMS), CTX_BASE)
    foot = m.element("R1 retaining wall footing 0+00.00")
    xs = [p[0] for p in _corners(foot)]
    ys = [p[1] for p in _corners(foot)]
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(8.0)
    # toe C = 2 ft to the Lt (west), heel B = 4 ft to the Rt (east)
    assert min(xs) == pytest.approx(-2.0) and max(xs) == pytest.approx(4.0)
    assert run_pre(m).passed
