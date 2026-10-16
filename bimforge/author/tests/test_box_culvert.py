import uuid
import pytest
from bimforge.author.families.box_culvert import build
from bimforge.author.gate import run_pre
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="bc", guid_ns=uuid.UUID(int=9))

# Real D80 single 8x5 cover-10 row; illustrative double.
_ROW = {"wall_t_ft": 0.5833, "top_slab_ft": 0.7917, "bot_slab_ft": 0.7083,
        "a": "#6@4.5", "b": "#6@5", "e": "#4@9", "conc_cf_lf": 19.6}
TABLE = {
    "single": {"8x5": {"covers": {10: {**_ROW, "lb_per_lf": 229}}}},
    "double": {"8x5": {"covers": {10: {**_ROW, "conc_cf_lf": 35.4,
                                       "lb_per_lf": 380}}}},
}

PARAMS = {
    "tables": TABLE,
    "culverts": [{"name": "C1", "cells": 1, "span_ft": 8.0, "height_ft": 5.0,
                  "earth_cover_ft": 10.0, "barrel_length_ft": 20.0}],
}


def test_single_box_concrete_volume():
    m = build(PARAMS, CTX)
    conc = m.element("C1 box culvert barrel")
    # area = 9.1666*6.5 - 40 = 19.583 sf ; x 20 ft barrel
    assert conc.quantities["volume_cf"] == pytest.approx(19.583 * 20.0, abs=0.5)
    assert run_pre(m).passed


def test_missing_params_raises():
    with pytest.raises(ValueError, match="missing"):
        build({"tables": TABLE}, CTX)


def test_rebar_weight_from_lb_per_lf():
    m = build(PARAMS, CTX)
    steel = m.element("C1 box culvert reinforcing")
    assert steel.ifc_class == "IfcReinforcingBar"
    assert steel.quantities["weight_lb"] == pytest.approx(229.0 * 20.0)
    assert run_pre(m).passed


def test_double_box_two_cell_volume():
    params = {"tables": TABLE,
              "culverts": [{"name": "C2", "cells": 2, "span_ft": 8.0,
                            "height_ft": 5.0, "earth_cover_ft": 10.0,
                            "barrel_length_ft": 20.0}]}
    m = build(params, CTX)
    conc = m.element("C2 box culvert barrel")
    # area = 17.75*6.5 - 80 = 35.375 sf ; x 20 ft
    assert conc.quantities["volume_cf"] == pytest.approx(35.375 * 20.0, abs=0.5)
    assert run_pre(m).passed


def test_box_culvert_paycodes_classify():
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-box-culvert.paycodes.yaml")
    pc = pc_mod.load(p)
    m = build(PARAMS, CTX)
    pc_mod.apply(m, pc)
    conc = m.element("C1 box culvert barrel")
    steel = m.element("C1 box culvert reinforcing")
    assert conc.classifications == ["STRUCT-CONC-BC"]
    assert steel.classifications == ["BAR-STEEL-BC"]


def test_box_culvert_example_spec_builds_check_only():
    from pathlib import Path
    from bimforge.author.families.registry import build_from_spec
    spec = (Path(__file__).resolve().parents[1]
            / "examples" / "caltrans-box-culvert.spec.yaml")
    assert build_from_spec(spec, check_only=True) == 0


def test_box_culvert_example_full_build(tmp_path):
    from pathlib import Path
    import yaml
    from bimforge.author.families.registry import build_from_spec
    src = (Path(__file__).resolve().parents[1]
           / "examples" / "caltrans-box-culvert.spec.yaml")
    spec = yaml.safe_load(src.read_text())
    spec["params"]["tables_file"] = str(
        (src.parent / spec["params"]["tables_file"]).resolve())
    spec["paycodes"] = str((src.parent / spec["paycodes"]).resolve())
    spec["outputs"] = {
        "dxf": str(tmp_path / "bc.dxf"),
        "ifc": str(tmp_path / "bc.ifc"),
        "takeoff_map": str(tmp_path / "bc-takeoff-map.yaml"),
    }
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(spec))
    assert build_from_spec(p, check_only=False) == 0
    assert (tmp_path / "bc.ifc").exists()
