import copy
import math
import uuid
import pytest
from bimforge.author.gate import run_pre
from bimforge.author.project import ProjectContext
from bimforge.author.families.culvert_headwall import build

CTX = ProjectContext(name="hw", guid_ns=uuid.UUID(int=90))
B3 = {"type_1_case_1": {"table": {
    "6": {"W_ft": 5.0, "C_ft": 1.5, "B_ft": 3.5, "T_ft": 1.0, "F_ft": 1.0,
          "batter": "NONE"}}}}
SCHED = {"wall_vert": {"size": 5, "spacing_in": 12},
         "footing": {"size": 5, "spacing_in": 12},
         "pipe_dist": {"size": 6, "count": 2},
         "wing_vert": {"size": 4, "spacing_in": 12}}
SPEC = {"tables": {"type_1_case_1": B3["type_1_case_1"],
                   "d90": {"schedule": SCHED,
                           "wingwalls": {"A": {"angle_deg": 30.0, "length_ft": 8.0,
                                               "h_far_ft": 1.0, "t_ft": 1.0}}}},
        "structures": [
            {"name": "HW1", "kind": "headwall", "design_h_ft": 6.0,
             "length_ft": 10.0,
             "pipe": {"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
             "wingwalls": [{"type": "A", "side": "left"},
                           {"type": "A", "side": "right"}]}]}


TCB_836 = {
    "barrier_type": "836", "h_ft": 3.0, "per_standard_plan": "B11-80",
    "shape": "single_slope",
    "profile": [[0.0, 0.0], [0.0, 1.8333], [-0.25, 1.8333], [-0.3333, 1.9167],
                [-0.3333, 2.8958], [-0.2292, 3.0], [0.8542, 3.0],
                [0.9507, 2.9177], [1.4167, 0.0]],
    "concrete_cf_per_lf": 3.908, "haunch_ft": 1.0,
    "bars": {"longitudinal": {"size": 5, "count": 12},
             "ties": {"size": 5, "spacing_in": 8},
             "haunch": {"cont": {"size": 4, "count": 2},
                        "dowels": {"size": 5, "spacing_in": 12, "count": 3,
                                   "length_ft": 3.0}}}}


def _typec_spec():
    d90 = {"schedule": SCHED, "type_c_barrier": TCB_836,
           "wingwalls": {"C": {"angle_deg": 30.0, "length_ft": 8.0,
                               "h_far_ft": 1.0, "t_ft": 1.0}}}
    return {"tables": {"type_1_case_1": B3["type_1_case_1"], "d90": d90},
            "structures": [{"name": "HWC", "kind": "headwall", "design_h_ft": 6.0,
                            "length_ft": 10.0,
                            "pipe": {"dia_ft": 3.0, "center_ft": 5.0,
                                     "material": "rc"},
                            "wingwalls": [{"type": "C", "side": "left"}]}]}


def test_missing_structures_raises():
    with pytest.raises(ValueError, match="missing"):
        build({}, CTX)


def test_missing_schedule_raises():
    # a project merging only the fixed-rules catalog (no d90.schedule) must
    # fail loud rather than silently emit zero pay steel.
    spec = {"tables": {"type_1_case_1": B3["type_1_case_1"], "d90": {}},
            "structures": [{"name": "HW1", "kind": "headwall",
                            "design_h_ft": 6.0, "length_ft": 10.0,
                            "pipe": {"dia_ft": 3.0, "center_ft": 5.0,
                                     "material": "rc"},
                            "wingwalls": []}]}
    with pytest.raises(ValueError, match="schedule"):
        build(spec, CTX)


def test_headwall_concrete_and_gate():
    m = build(SPEC, CTX)
    panel = m.element("HW1 headwall panel")
    foot = m.element("HW1 footing")
    assert panel.ifc_class == "IfcWall"
    assert panel.quantities["volume_cf"] > 0
    # Footing is now ONE mitred toe/heel run under headwall + both wingwalls;
    # its volume is the mitred plan x F, NOT a plain 10x5x1 box -- just assert
    # it is a real positive quantity and the gate passes.
    assert foot.ifc_class == "IfcFooting"
    assert foot.quantities["volume_cf"] > 0
    assert "width_ft" not in foot.quantities and "height_ft" not in foot.quantities
    assert run_pre(m).passed
    # The mitred footing and the battered-loft wingwalls carry length+volume
    # only (an irregular prism must not declare L x W x H). The L x W x H ==
    # volume invariant is exercised on the one element that DOES declare all
    # three dims: the clean-box Type-C barrier. (No barrier in SPEC, so the
    # loop is exercised by the Type-C tests below.)
    for nm in m.elements:
        q = nm.quantities
        if all(k in q for k in ("length_ft", "width_ft", "height_ft",
                                "volume_cf")):
            assert (q["length_ft"] * q["width_ft"] * q["height_ft"]
                    == pytest.approx(q["volume_cf"]))


def test_wingwalls_and_reinforcing_emitted():
    m = build(SPEC, CTX)
    assert m.element("HW1 wingwall left").quantities["volume_cf"] > 0
    assert m.element("HW1 wingwall right").quantities["volume_cf"] > 0
    rebar = [e for e in m.elements if e.ifc_class == "IfcReinforcingBar"]
    assert rebar and all(e.quantities["weight_lb"] > 0 for e in rebar)


def test_endwall_kind_builds():
    spec = {**SPEC, "structures": [{**SPEC["structures"][0],
                                    "name": "EW1", "kind": "endwall"}]}
    m = build(spec, CTX)
    assert m.element("EW1 headwall panel").quantities["volume_cf"] > 0
    assert run_pre(m).passed


def test_wingwalls_placed_inboard_mirror():
    # both wingwall plates must sit on the SAME (inboard, +y toward the footing)
    # side of the panel line, i.e. their thickness offset is +y, not one +y and
    # one -y. Guards the Task-2 "+90-CCW normal is the caller's job" contract.
    # (Prism exposes its plan polygon as `.base`; there is no `.plan` attr.)
    m = build(SPEC, CTX)
    for side in ("left", "right"):
        plate = m.element(f"HW1 wingwall {side}").geometry
        ys = [p[1] for p in plate.base]
        assert max(ys) > 1e-9, f"{side} wingwall must extend to +y (inboard)"
        assert min(ys) >= -1e-9, f"{side} wingwall must not cross to -y (outboard)"


def test_wingwall_bad_side_raises():
    # a mistyped side ("Right", "rgt") must fail loud, not silently emit
    # mirrored geometry (the anchor/taper handedness keys off the exact string).
    spec = {**SPEC, "structures": [{**SPEC["structures"][0],
                                    "wingwalls": [{"type": "A", "side": "Right"}]}]}
    with pytest.raises(ValueError, match="side must be"):
        build(spec, CTX)


def test_wingwalls_taper_full_height_at_headwall():
    # The y >= 0 check above is blind to which END is full height (the volume is
    # a mean, order-independent). Pin the taper on the BatteredWall's own
    # top_profile: full height (wall_H) at the panel-connection x, daylighting
    # to h_far at the free-end x -- for BOTH wings. A plate that forgot to place
    # full height at the headwall (short there, full at the channel) fails this.
    # Measured at the wall's OWN two ends, not sampled from `top_profile` at
    # hand-computed plan stations. #314 moved the lol from the earth face to the
    # creek face: the body did not move, but its key stations shifted by one
    # wall thickness along the leg normal, so sampling at the old stations reads
    # mid-wall and fails for no physical reason. The height at its own ends is
    # what this test is about.
    wall_h, h_far_ft = 6.0, 1.0
    m = build(SPEC, CTX)
    for side in ("left", "right"):
        plate = m.element(f"HW1 wingwall {side}").geometry
        # sections run in lol order; each is [lol_base, off_base, off_top, lol_top]
        heights = [max(q[2] for q in s) - min(q[2] for q in s)
                   for s in plate._sections]
        corner = 0 if side == "right" else -1       # the end that meets the panel
        free = -1 if side == "right" else 0
        assert heights[corner] == pytest.approx(wall_h), (
            f"{side} wingwall must be full height at the headwall, got "
            f"{heights[corner]:.4f}")
        assert heights[free] == pytest.approx(h_far_ft), (
            f"{side} wingwall must daylight to h_far at the free end, got "
            f"{heights[free]:.4f}")
        assert heights in (sorted(heights), sorted(heights, reverse=True)), (
            f"{side} wingwall top must taper monotonically: {heights}")


def test_headwall_paycodes_classify():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-d90-headwall.paycodes.yaml")
    pc = pc_mod.load(p)
    m = build(SPEC, CTX)
    pc_mod.apply(m, pc)
    assert m.element("HW1 headwall panel").classifications == ["STRUCT-CONC-HW"]
    steel = m.element("HW1 headwall reinforcing wall_vert #5").classifications
    assert steel == ["BAR-STEEL-HW"]


def test_headwall_example_spec_builds_check_only():
    from pathlib import Path
    from bimforge.author.families.registry import build_from_spec
    spec = (Path(__file__).resolve().parents[1]
            / "examples" / "caltrans-d90-headwall.spec.yaml")
    assert build_from_spec(spec, check_only=True) == 0


def test_headwall_example_full_build_with_bbs(tmp_path):
    from pathlib import Path
    import yaml
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook
    from bimforge.author.families.registry import build_from_spec
    src = (Path(__file__).resolve().parents[1]
           / "examples" / "caltrans-d90-headwall.spec.yaml")
    spec = yaml.safe_load(src.read_text())
    spec["params"]["tables_file"] = str(
        (src.parent / spec["params"]["tables_file"]).resolve())
    spec["paycodes"] = str((src.parent / spec["paycodes"]).resolve())
    spec["outputs"] = {"ifc": str(tmp_path / "d.ifc"),
                       "takeoff_map": str(tmp_path / "d-map.yaml"),
                       "bbs": str(tmp_path / "d.bbs.xlsx")}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    assert build_from_spec(p, check_only=False) == 0
    assert (tmp_path / "d.ifc").exists()
    wb = load_workbook(tmp_path / "d.bbs.xlsx")
    rows = list(wb.active.iter_rows(values_only=True))
    assert rows[0] == ("Mark", "Size", "Count", "Length (ft)", "Weight (lb)")
    assert rows[-1][0] == "TOTAL" and rows[-1][4] > 0


def test_headwall_steel_weight_rolls_up_nonzero():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-d90-headwall.paycodes.yaml")
    m = build(SPEC, CTX)
    pc_mod.apply(m, pc_mod.load(p))
    steel_els = [e for e in m.elements
                 if e.classifications == ["BAR-STEEL-HW"]]
    assert steel_els, "no element classified as BAR-STEEL-HW (regex miss?)"
    total = sum(e.quantities["weight_lb"] for e in steel_els)
    assert total > 0
    # every reinforcing element must be classified steel, none miscoded concrete
    for e in m.elements:
        if "headwall reinforcing" in e.name:
            assert e.classifications == ["BAR-STEEL-HW"], e.name


def test_headwall_concrete_weight_rolls_up_nonzero():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-d90-headwall.paycodes.yaml")
    # Type-C spec so the barrier concrete path is also exercised
    d90 = {"schedule": SCHED, "type_c_barrier": TCB_836,
           "wingwalls": {"C": {"angle_deg": 30.0, "length_ft": 8.0,
                               "h_far_ft": 1.0, "t_ft": 1.0}}}
    spec = {"tables": {"type_1_case_1": B3["type_1_case_1"], "d90": d90},
            "structures": [
                {"name": "HWC", "kind": "headwall", "design_h_ft": 6.0,
                 "length_ft": 10.0,
                 "pipe": {"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
                 "wingwalls": [{"type": "C", "side": "left"},
                               {"type": "C", "side": "right"}]}]}
    m = build(spec, CTX)
    pc_mod.apply(m, pc_mod.load(p))
    conc = [e for e in m.elements if e.classifications == ["STRUCT-CONC-HW"]]
    assert conc and sum(e.quantities["volume_cf"] for e in conc) > 0
    names = {e.name for e in conc}
    # ONE continuous rail across both Type-C wings + the headwall
    assert {"HWC headwall panel", "HWC footing",
            "HWC wingwall left", "HWC wingwall right",
            "HWC headwall barrier rail"} <= names


def test_barrier_is_swept_836_rail_not_a_box():
    # _typec_spec has a LEFT Type-C wing -> the rail crosses the headwall too:
    # left wing (8) + headwall (10) = 18 ft continuous.
    m = build(_typec_spec(), CTX)
    bar = m.element("HWC headwall barrier rail")
    # length + volume only (irregular prism) -- no box width/height keys
    assert "width_ft" not in bar.quantities and "height_ft" not in bar.quantities
    assert bar.quantities["length_ft"] == pytest.approx(18.0)
    # real 836 section (~3.9 sf) + the ~1.03 sf Section A-A haunch (1 ft vertical
    # + a 1:1 soffit to the wall) per LF -- a real swept section, not a box
    per_lf = bar.quantities["volume_cf"] / 18.0
    assert 4.5 < per_lf < 5.2


def test_barrier_base_rides_the_sloping_wingwall_top():
    m = build(_typec_spec(), CTX)
    zs = [v[2] for sol in m.element("HWC headwall barrier rail").geometry.body_solids()
          for v in sol["verts"]]
    # top at the headwall corner = wall.H + 3.0; the base rides the wall top down
    # to h_far=1.0 at the free end, and the haunch (1 ft vertical + a 1:1 soffit
    # to the wall) drops below that.
    assert max(zs) == pytest.approx(6.0 + 3.0, abs=1e-6)
    assert min(zs) < 1.0                                    # haunch drops below the free-end base


def test_type_c_barrier_missing_source_still_raises():
    d90 = {"schedule": SCHED,   # no type_c_barrier
           "wingwalls": {"C": {"angle_deg": 30.0, "length_ft": 8.0,
                               "h_far_ft": 1.0, "t_ft": 1.0}}}
    spec = {"tables": {"type_1_case_1": B3["type_1_case_1"], "d90": d90},
            "structures": [{"name": "HWC", "kind": "headwall", "design_h_ft": 6.0,
                            "length_ft": 10.0,
                            "pipe": {"dia_ft": 3.0, "center_ft": 5.0,
                                     "material": "rc"},
                            "wingwalls": [{"type": "C", "side": "left"}]}]}
    with pytest.raises(ValueError, match="Type C wall requires a barrier"):
        build(spec, CTX)


def test_barrier_concrete_and_steel_classify_correctly():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-d90-headwall.paycodes.yaml")
    m = build(_typec_spec(), CTX)
    pc_mod.apply(m, pc_mod.load(p))
    assert m.element("HWC headwall barrier rail").classifications == ["STRUCT-CONC-HW"]
    tie = next(e for e in m.elements if " tie #" in e.name)
    assert tie.classifications == ["BAR-STEEL-HW"]
    dowel = next(e for e in m.elements if "haunch_dowel" in e.name)
    assert dowel.classifications == ["BAR-STEEL-HW"]


def test_type_c_barrier_missing_source_raises():
    # Type C's rule is barrier: required. With NEITHER a per-wingwall barrier
    # dict NOR a d90.type_c_barrier catalog entry, the family must fail loud
    # rather than silently drop the barrier concrete.
    d90 = {"schedule": SCHED,  # no 'type_c_barrier' key
           "wingwalls": {"C": {"angle_deg": 30.0, "length_ft": 8.0,
                               "h_far_ft": 1.0, "t_ft": 1.0}}}  # no 'barrier'
    spec = {"tables": {"type_1_case_1": B3["type_1_case_1"], "d90": d90},
            "structures": [
                {"name": "HWC", "kind": "headwall", "design_h_ft": 6.0,
                 "length_ft": 10.0,
                 "pipe": {"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
                 "wingwalls": [{"type": "C", "side": "left"}]}]}
    with pytest.raises(ValueError, match="Type C wall requires a barrier"):
        build(spec, CTX)


def test_footing_self_intersection_raises():
    # A short, steeply-flared wingwall on a wide toe folds the mitred toe/heel
    # plan ring back over itself; the family must fail loud rather than emit a
    # tangled footing solid. Guards the self-intersection check (which otherwise
    # never fires on any passing test -- a vacuous safety net). This config
    # (60 deg flare, 2 ft legs, C=8) self-intersects WITHOUT tripping
    # mitre_offset's ~135 deg limit first, so it exercises the guard itself.
    big_c = {"type_1_case_1": {"table": {
        "6": {"W_ft": 11.5, "C_ft": 8.0, "B_ft": 3.5, "T_ft": 1.0, "F_ft": 1.0,
              "batter": "NONE"}}}}
    spec = {"tables": {"type_1_case_1": big_c["type_1_case_1"],
                       "d90": {"schedule": SCHED,
                               "wingwalls": {"A": {"angle_deg": 60.0,
                                                   "length_ft": 2.0,
                                                   "h_far_ft": 1.0, "t_ft": 1.0}}}},
            "structures": [{"name": "HW1", "kind": "headwall", "design_h_ft": 6.0,
                            "length_ft": 10.0,
                            "pipe": {"dia_ft": 3.0, "center_ft": 5.0,
                                     "material": "rc"},
                            "wingwalls": [{"type": "A", "side": "left"},
                                          {"type": "A", "side": "right"}]}]}
    with pytest.raises(ValueError, match="self-intersect"):
        build(spec, CTX)


def test_headwall_pipe_dist_rc_vs_metal():
    # RC pipe emits pipe-distribution bars; metal pipe emits none (manufacturer
    # hook bolts) -- pins the branch the example spec (HWIN rc / EWOUT metal)
    # was built to demonstrate.
    rc = build(SPEC, CTX)
    assert any("pipe_dist" in e.name for e in rc.elements
               if e.ifc_class == "IfcReinforcingBar")
    metal_spec = {**SPEC, "structures": [
        {**SPEC["structures"][0],
         "pipe": {**SPEC["structures"][0]["pipe"], "material": "metal"}}]}
    metal = build(metal_spec, CTX)
    assert not any("pipe_dist" in e.name for e in metal.elements
                   if e.ifc_class == "IfcReinforcingBar")


def test_footing_runs_under_headwall_and_both_wingwalls():
    m = build(SPEC, CTX)
    foot = m.element("HW1 footing").geometry
    xs = [p[0] for p in foot.base]
    assert min(xs) < -1.0 and max(xs) > 10.0 + 1.0      # extends under both wings
    assert m.element("HW1 footing").quantities["volume_cf"] > 0


def test_wingwall_stems_are_battered_lofts_inboard():
    m = build(SPEC, CTX)
    for side in ("left", "right"):
        w = m.element(f"HW1 wingwall {side}")
        assert w.ifc_class == "IfcWall" and w.quantities["volume_cf"] > 0
        ys = [p[1] for p in w.geometry.base]
        assert max(ys) > 1e-9 and min(ys) >= -1e-9        # inboard +Y


def test_fl_places_pipe_invert_at_flowline():
    # FL = pipe invert. center_z defaults to r + 0.5 (r=1.5 -> invert sits 0.5 ft
    # above the local datum), so the structure lifts by fl - 0.5 and the EMITTED
    # invert (z_ft + invert_local) lands EXACTLY at fl_elev_ft. Bearing/offset
    # are still set; the two structures are opposites, placed apart.
    spec = {**SPEC, "structures": [
        {**SPEC["structures"][0], "name": "HWIN", "kind": "headwall",
         "fl_elev_ft": 100.0, "bearing_deg": 0.0, "position_ft": [0.0, 0.0]},
        {**SPEC["structures"][0], "name": "EWOUT", "kind": "endwall",
         "fl_elev_ft": 96.0, "bearing_deg": 180.0, "position_ft": [0.0, 40.0]}]}
    m = build(spec, CTX)
    invert_local = (1.5 + 0.5) - 1.5                 # center_z(default) - r = 0.5
    hw = [e for e in m.elements if e.name.startswith("HWIN ")]
    ew = [e for e in m.elements if e.name.startswith("EWOUT ")]
    assert hw and ew
    # emitted invert == z_ft + invert_local must equal fl_elev_ft (reverting the
    # fix to z_ft == fl_elev would land the invert at 100.5 and fail here).
    assert all(e.bearing_deg == 0.0 and e.y_ft == 0.0
               and e.z_ft + invert_local == pytest.approx(100.0) for e in hw)
    assert all(e.bearing_deg == 180.0 and e.y_ft == 40.0
               and e.z_ft + invert_local == pytest.approx(96.0) for e in ew)
    assert run_pre(m).passed                          # placement doesn't break gate


def test_endwall_fl_above_headwall_raises():
    with pytest.raises(ValueError, match="EW .* HW|flow line"):
        build({**SPEC, "structures": [
            {**SPEC["structures"][0], "name": "A", "kind": "headwall",
             "fl_elev_ft": 90.0},
            {**SPEC["structures"][0], "name": "B", "kind": "endwall",
             "fl_elev_ft": 95.0}]}, CTX)     # outlet higher than inlet -> raise


def test_placement_default_zero_is_unplaced():
    # default SPEC (no bearing/offset/FL) leaves every element at the origin,
    # so existing single-structure output is unchanged.
    m = build(SPEC, CTX)
    for e in m.elements:
        assert e.bearing_deg == 0.0 and e.x_ft == 0.0 and e.y_ft == 0.0 and e.z_ft == 0.0


def test_headwall_example_full_build_qto_and_paycode_rollup(tmp_path):
    # Companion to the BBS full-build test: the same example must also surface a
    # positive concrete volume in the QTO xlsx and roll BOTH pay quantities up
    # nonzero through the example paycodes (concrete CF and steel LB).
    from pathlib import Path
    import yaml
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook
    from bimforge.author.families.registry import build_from_spec, load_spec
    from bimforge.author import paycodes as pc_mod
    from bimforge.author.project import ProjectContext
    src = (Path(__file__).resolve().parents[1]
           / "examples" / "caltrans-d90-headwall.spec.yaml")
    spec = yaml.safe_load(src.read_text())
    spec["params"]["tables_file"] = str(
        (src.parent / spec["params"]["tables_file"]).resolve())
    spec["paycodes"] = str((src.parent / spec["paycodes"]).resolve())
    spec["outputs"] = {"ifc": str(tmp_path / "d.ifc"),
                       "takeoff_map": str(tmp_path / "d-map.yaml"),
                       "qto": str(tmp_path / "d.qto.xlsx"),
                       "bbs": str(tmp_path / "d.bbs.xlsx")}
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    assert build_from_spec(p, check_only=False) == 0     # gate passes / rc 0
    assert (tmp_path / "d.ifc").exists()

    # QTO surfaces a positive concrete quantity (STRUCT-CONC-HW, unit CY).
    wb = load_workbook(tmp_path / "d.qto.xlsx")
    summary = {r[0]: r for r in wb["Summary"].iter_rows(values_only=True)}
    conc_row = summary["STRUCT-CONC-HW"]
    assert conc_row[4] == "CY" and conc_row[3] > 0        # Modelled CY positive

    # BBS TOTAL weight > 0.
    bbs = load_workbook(tmp_path / "d.bbs.xlsx")
    rows = list(bbs.active.iter_rows(values_only=True))
    assert rows[-1][0] == "TOTAL" and rows[-1][4] > 0

    # Both pay quantities roll up nonzero through paycodes.apply: concrete
    # volume_cf for STRUCT-CONC-HW AND steel weight_lb for BAR-STEEL-HW.
    full = load_spec(src)
    ctx = ProjectContext.from_spec(full["project"])
    pc = pc_mod.load(full["paycodes"])
    m = build(full["params"], ctx)
    pc_mod.apply(m, pc)
    conc = [e for e in m.elements if e.classifications == ["STRUCT-CONC-HW"]]
    steel = [e for e in m.elements if e.classifications == ["BAR-STEEL-HW"]]
    assert conc and sum(e.quantities["volume_cf"] for e in conc) > 0
    assert steel and sum(e.quantities["weight_lb"] for e in steel) > 0


def test_swept_wingwall_footing_descends():
    # base_drop_ft descends the footing top along the wing; free end sits below 0.
    spec = {**SPEC, "structures": [{**SPEC["structures"][0],
        "wingwalls": [{"type": "A", "side": "left", "base_drop_ft": 3.0, "footing": "swept"},
                      {"type": "A", "side": "right", "base_drop_ft": 3.0, "footing": "swept"}]}]}
    m = build(spec, CTX)
    foot = m.element("HW1 footing").geometry
    zbots = [v[2] for sec in foot._sections for v in sec]   # any footing z
    assert min(zbots) < -1.0                                  # descended below datum
    assert run_pre(m).passed


# --- #314: which FACE batters ------------------------------------------------

#: B3-1A Type 1 Case 1 row 6 with the batter the sheet actually gives, in place
#: of the shipped fixture's "NONE". That NONE is why nothing here caught #314:
#: with zero batter the two faces are indistinguishable, so no fixture in this
#: file could tell a wall battered on the creek side from one battered on the
#: earth side. The flare was never the missing ingredient -- SPEC already flares
#: both wings 30 degrees -- the batter was.
def _battered_spec():
    spec = copy.deepcopy(SPEC)
    spec["tables"]["type_1_case_1"]["table"]["6"]["batter"] = "0.5:12"
    return spec


def test_wingwall_stems_stand_plumb_on_the_channel_and_batter_toward_the_earth():
    """#314. `BatteredWall`'s lol IS its plumb face and it batters the face it
    offsets toward, so handing it the earth-side line battered the exposed CREEK
    face and stood the wall plumb on the retained earth -- backwards to B3-1A
    Type 1. The magnitude was right (0.25 ft over a 6 ft wall, 0.5:12), only the
    side, so no volume and no length moved and nothing noticed. On a flared wing
    each base then stood PROUD of the panel's exposed face and crossed back
    inside it partway up: a visible non-plumb twist on the front elevation.

    -Y is the retained earth here and +Y the channel, fixed by the footing: it
    is built `side=-1.0`, which puts the toe (C) on +Y and the heel (B) on -Y.
    """
    m = build(_battered_spec(), CTX)
    for side in ("left", "right"):
        plate = m.element(f"HW1 wingwall {side}").geometry
        assert plate.batter == pytest.approx(0.5 / 12.0), "fixture lost its batter"
        for i, s in enumerate(plate._sections):
            lol_base, off_base, off_top, lol_top = s
            # the lol face is PLUMB: identical plan position at base and top
            assert lol_base[0] == pytest.approx(lol_top[0], abs=1e-12)
            assert lol_base[1] == pytest.approx(lol_top[1], abs=1e-12), (
                f"{side} section {i}: the lol face is not plumb")
            # the offset face BATTERS by exactly H*batter ...
            spread = math.hypot(off_base[0] - off_top[0], off_base[1] - off_top[1])
            h = lol_top[2] - lol_base[2]
            assert spread == pytest.approx(h * plate.batter, abs=1e-9), (
                f"{side} section {i}: {spread:.6f} ft of batter over {h:.4f} ft "
                f"of wall is not 0.5:12")
            # ... and it leans toward the retained earth, -Y
            if h > 1e-9:
                assert off_base[1] < off_top[1] - 1e-9, (
                    f"{side} section {i}: the base thickening leans to +Y, the "
                    f"channel. B3-1A batters the RETAINED-EARTH face and keeps "
                    f"the exposed face plumb.")


def test_putting_the_batter_on_the_right_face_does_not_change_the_volume():
    """The fix slides the lol one wall thickness onto the creek face and offsets
    back the other way, so the top-of-wall footprint is identical and only the
    base thickening swaps sides. The trapezoid section is untouched, which is
    why this was safe to change on a live family: it is the same concrete.

    Checked against the closed form rather than against a rebuilt "old" wall,
    because that comparison cannot be made exact -- shifting every coordinate by
    a foot re-rounds the divergence-theorem sum and the two agree only to ~2e-10
    relative. The closed form belongs to neither convention.
    """
    from bimforge.author.primitives import BatteredWall, outward_normals
    m = build(_battered_spec(), CTX)
    T, batter, wl = 1.0, 0.5 / 12.0, 8.0
    h_hi, h_lo = 6.0, 1.0
    # A trapezoid section (t_top + H*batter wide) swept along a straight leg
    # whose H ramps h_hi -> h_lo integrates to
    #     wl * (T*mean(H) + batter*mean(H^2)/2),   mean(H^2) = (a^2+ab+b^2)/3.
    mean_h = (h_hi + h_lo) / 2.0
    mean_h2 = (h_hi ** 2 + h_hi * h_lo + h_lo ** 2) / 3.0
    expect = wl * (T * mean_h + batter * mean_h2 / 2.0)
    assert expect == pytest.approx(30.38888889, abs=1e-7)   # guards the algebra
    for side in ("left", "right"):
        fixed = m.element(f"HW1 wingwall {side}").geometry
        assert fixed.volume_cf == pytest.approx(expect, rel=1e-9), (
            f"{side}: {fixed.volume_cf:.6f} cf is not the trapezoid integral "
            f"{expect:.6f} cf, so the section changed and not merely its side")
        # ... and the top of wall occupies the same plan footprint it did before
        # the fix, which is what makes the volume result mean something: the
        # wall did not move, only which face carries the batter.
        n_earth = outward_normals(fixed.lol, +1.0)[0]
        dx, dy = n_earth[0] * T, n_earth[1] * T
        was = BatteredWall(
            "pre-#314", lol=[(x + dx, y + dy) for (x, y) in fixed.lol],
            top_profile=[(k + dx, e) for (k, e) in fixed.top_profile],
            key_index=0, base_el=0.0, t_top=T, batter=batter, side=-1.0,
            base_profile=(None if fixed.base_profile is None else
                          [(k + dx, e) for (k, e) in fixed.base_profile]))
        top_fixed = sorted((round(q[0], 9), round(q[1], 9))
                           for s in fixed._sections for q in (s[2], s[3]))
        top_was = sorted((round(q[0], 9), round(q[1], 9))
                         for s in was._sections for q in (s[2], s[3]))
        assert top_fixed == top_was, f"{side}: the wall moved"
