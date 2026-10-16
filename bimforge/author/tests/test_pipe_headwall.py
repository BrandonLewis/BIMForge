import math
import uuid
import pytest
from bimforge.author.families.pipe_headwall import (
    build, circular_void, arch_void)
from bimforge.author.gate import run_pre
from bimforge.author.primitives import poly_area
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="hw", guid_ns=uuid.UUID(int=11))
TABLE = {"headwall": {
    "4-8": {"T_ft": 0.8333, "W_ft": 5.3333, "C_ft": 1.3333, "B_ft": 4.0,
            "F_ft": 1.0, "c": "#4@12", "d": "#5@8",
            "conc_cy_lf": 0.37, "reinf_lb_lf": 37}}}
PARAMS = {"tables": TABLE, "headwalls": [
    {"name": "HW1", "form": "straight", "design_h_ft": 4.6, "length_ft": 8.0,
     "openings": [{"shape": "circular", "dia_ft": 2.0, "center_ft": 4.0}]}]}


def test_circular_void_area():
    ring = circular_void(2.0, cu=4.0, cz=3.0, n=64)
    assert poly_area(ring) == pytest.approx(math.pi * 1.0 ** 2, rel=0.01)  # r=1
    xs = [p[0] for p in ring]
    assert min(xs) == pytest.approx(3.0, abs=0.02)   # cu - r
    assert max(xs) == pytest.approx(5.0, abs=0.02)   # cu + r


def test_arch_void_area_and_flat_invert():
    ring = arch_void(span=4.0, rise=3.0, cu=5.0, cz_invert=1.0, n=64)
    assert poly_area(ring) == pytest.approx(math.pi * 2.0 * 3.0 / 2.0, rel=0.02)
    zs = [p[1] for p in ring]
    assert min(zs) == pytest.approx(1.0, abs=1e-6)   # flat invert at cz_invert
    assert max(zs) == pytest.approx(4.0, abs=0.02)   # invert + rise


def test_straight_missing_params_raises():
    with pytest.raises(ValueError, match="missing"):
        build({"tables": TABLE}, CTX)


def test_straight_stem_and_footing_volumes():
    m = build(PARAMS, CTX)
    stem = m.element("HW1 headwall stem")
    foot = m.element("HW1 headwall footing")
    T, Hs, L, W, F = 0.8333, 5.6667, 8.0, 5.3333, 1.0     # H(4-8)=4.6667 +1
    hole = math.pi * 1.0 ** 2                              # dia 2 -> r 1
    assert stem.quantities["volume_cf"] == pytest.approx((L * Hs - hole) * T, abs=0.1)
    assert foot.quantities["volume_cf"] == pytest.approx(L * W * F, abs=0.05)
    assert run_pre(m).passed


def test_straight_reinforcing_weight():
    m = build(PARAMS, CTX)
    steel = m.element("HW1 headwall reinforcing")
    assert steel.ifc_class == "IfcReinforcingBar"
    assert steel.quantities["weight_lb"] == pytest.approx(37.0 * 8.0)
    assert run_pre(m).passed


def test_double_opening_two_holes():
    params = {"tables": TABLE, "headwalls": [
        {"name": "HW2", "form": "straight", "design_h_ft": 4.6, "length_ft": 12.0,
         "openings": [{"shape": "circular", "dia_ft": 2.0, "center_ft": 3.0},
                      {"shape": "circular", "dia_ft": 2.0, "center_ft": 9.0}]}]}
    m = build(params, CTX)
    stem = m.element("HW2 headwall stem")
    T, Hs, L = 0.8333, 5.6667, 12.0
    holes = 2 * math.pi * 1.0 ** 2
    assert stem.quantities["volume_cf"] == pytest.approx((L * Hs - holes) * T, abs=0.1)
    assert run_pre(m).passed


def test_L_return_adds_leg_and_reinf():
    params = {"tables": TABLE, "headwalls": [
        {"name": "HWL", "form": "L", "design_h_ft": 4.6, "length_ft": 8.0,
         "return_len_ft": 7.0,
         "openings": [{"shape": "circular", "dia_ft": 2.0, "center_ft": 4.0}]}]}
    m = build(params, CTX)
    rstem = m.element("HWL headwall return stem")
    rfoot = m.element("HWL headwall return footing")
    T, Hs, W, F, RL = 0.8333, 5.6667, 5.3333, 1.0, 7.0
    assert rstem.quantities["volume_cf"] == pytest.approx(RL * T * Hs, abs=0.1)
    assert rfoot.quantities["volume_cf"] == pytest.approx(RL * W * F, abs=0.05)
    steel = m.element("HWL headwall reinforcing")
    assert steel.quantities["weight_lb"] == pytest.approx(37.0 * (8.0 + 7.0))
    assert run_pre(m).passed


def test_headwall_paycodes_classify():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-pipe-headwall.paycodes.yaml")
    pc = pc_mod.load(p)
    m = build(PARAMS, CTX)
    pc_mod.apply(m, pc)
    assert m.element("HW1 headwall stem").classifications == ["STRUCT-CONC-HW"]
    assert m.element("HW1 headwall footing").classifications == ["STRUCT-CONC-HW"]
    assert m.element("HW1 headwall reinforcing").classifications == ["BAR-STEEL-HW"]


def test_headwall_example_spec_builds_check_only():
    from pathlib import Path
    from bimforge.author.families.registry import build_from_spec
    spec = (Path(__file__).resolve().parents[1]
            / "examples" / "caltrans-pipe-headwall.spec.yaml")
    assert build_from_spec(spec, check_only=True) == 0


def test_headwall_example_full_build(tmp_path):
    from pathlib import Path
    import yaml
    from bimforge.author.families.registry import build_from_spec
    src = (Path(__file__).resolve().parents[1]
           / "examples" / "caltrans-pipe-headwall.spec.yaml")
    spec = yaml.safe_load(src.read_text())
    spec["params"]["tables_file"] = str(
        (src.parent / spec["params"]["tables_file"]).resolve())
    spec["paycodes"] = str((src.parent / spec["paycodes"]).resolve())
    spec["outputs"] = {
        "dxf": str(tmp_path / "hw.dxf"),
        "ifc": str(tmp_path / "hw.ifc"),
        "takeoff_map": str(tmp_path / "hw-takeoff-map.yaml"),
    }
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    assert build_from_spec(p, check_only=False) == 0
    assert (tmp_path / "hw.ifc").exists()


def test_headwall_example_fixture_schema():
    from pathlib import Path
    import yaml
    from bimforge.author.headwall_section import HeadwallSection, _parse_h_key
    from bimforge.author.box_section import parse_bar_spec
    t = yaml.safe_load((Path(__file__).resolve().parents[1] / "examples"
                        / "caltrans-pipe-headwall-tables.example.yaml").read_text())
    for key, row in t["headwall"].items():
        _parse_h_key(key)
        assert {"T_ft", "W_ft", "C_ft", "B_ft", "F_ft", "c", "d",
                "conc_cy_lf", "reinf_lb_lf"} <= set(row), key
        assert row["W_ft"] == pytest.approx(row["C_ft"] + row["B_ft"], abs=0.02)
        for mk in ("c", "d"):
            parse_bar_spec(row[mk])
        s = HeadwallSection(_parse_h_key(key), t)
        assert s.section_area_sf == pytest.approx(row["conc_cy_lf"] * 27.0, abs=0.15)
