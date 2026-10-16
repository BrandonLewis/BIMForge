import math
import uuid
import pytest
from bimforge.author.families.approach_slab import build
from bimforge.author.gate import run_pre
from bimforge.author.model import Element
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="b9", guid_ns=uuid.UUID(int=7))

TABLE = {
    "type_n_30": {"length_ft": 30.0, "thickness_ft": 1.25, "design_span_ft": 24.5,
                  "bars": {"bottom_main": "#10@6", "bottom_transverse": "#6@12",
                           "top_mat": "#5@18", "edge_cont": {"size": 5, "count": 4}},
                  "dowels": {"seat": "#5@12", "seat_len_ft": 2.0,
                             "diaphragm": "#5@9", "diaphragm_len_ft": 2.667}},
    "type_eq_10": {"length_ft": 10.0, "thickness_ft": 1.0, "design_span_ft": 7.83,
                   "bars": {"bottom_main": "#7@6", "bottom_transverse": "#6@12",
                            "top_mat": "#5@18", "edge_cont": {"size": 5, "count": 2}},
                   "dowels": {"seat": "#5@12", "seat_len_ft": 2.0,
                              "diaphragm": "#5@9", "diaphragm_len_ft": 2.667}},
}
ALIGN = {"pob": {"station": 0.0, "northing": 0.0, "easting": 0.0},
         "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 400.0}]}


def _params(**over):
    slab = {"name": "Abut 1", "slab_type": "type_n_30", "station": 100.0,
            "skew_deg": 0.0, "width_ft": 44.0, "approach": "ahead",
            "abutment_type": "seat", "joint": False, "drainage": False}
    slab.update(over)
    return {"alignment": ALIGN, "tables": TABLE, "slabs": [slab]}


def test_missing_params_raises():
    with pytest.raises(ValueError, match="missing"):
        build({"tables": TABLE}, CTX)


def test_slab_concrete_volume():
    m = build(_params(), CTX)
    slab = m.element("Abut 1 approach slab type_n_30")
    assert slab.ifc_class == "IfcSlab"
    assert slab.quantities["volume_cf"] == pytest.approx(30.0 * 44.0 * 1.25)
    assert run_pre(m).passed


def test_slab_area_is_length_times_width():
    m = build(_params(), CTX)
    slab = m.element("Abut 1 approach slab type_n_30")
    assert slab.quantities["area_sf"] == pytest.approx(30.0 * 44.0)


def test_skew_preserves_volume():
    m0 = build(_params(skew_deg=0.0), CTX)
    m30 = build(_params(skew_deg=30.0), CTX)
    v0 = m0.element("Abut 1 approach slab type_n_30").quantities["volume_cf"]
    v30 = m30.element("Abut 1 approach slab type_n_30").quantities["volume_cf"]
    assert v30 == pytest.approx(v0)  # shear preserves area


def test_skew_shears_the_footprint():
    from bimforge.author.families.approach_slab import _slab_corners

    class _A:  # minimal stand-in for Alignment at a point
        def point_az(self, s): return (0.0, 0.0, 0.0)   # (n, e, az) heading due north
        def left_normal(self, s): return (0.0, -1.0)     # unit left-normal

    sq = _slab_corners(_A(), 0.0, 0.0, 30.0, 44.0, "ahead")
    sk = _slab_corners(_A(), 0.0, 30.0, 30.0, 44.0, "ahead")
    # square slab: seat edge is perpendicular to travel -> both seat corners at n==0
    assert sq[0][0] == pytest.approx(0.0) and sq[3][0] == pytest.approx(0.0)
    # skewed slab: seat edge is sheared -> the two seat corners no longer share n
    assert abs(sk[0][0] - sk[3][0]) == pytest.approx(
        44.0 * math.tan(math.radians(30.0)), abs=1e-6)


def test_nonpositive_width_raises():
    with pytest.raises(ValueError, match="width_ft must be positive"):
        build(_params(width_ft=0.0), CTX)


def test_bad_approach_raises():
    with pytest.raises(ValueError, match="ahead"):
        build(_params(approach="sideways"), CTX)


def test_extreme_skew_raises():
    # skew near 90 deg makes width/cos(skew) blow up -- fail loud instead.
    with pytest.raises(ValueError, match="skew_deg"):
        build(_params(skew_deg=88.0), CTX)
    # the boundary (85) is still allowed
    assert build(_params(skew_deg=85.0), CTX).elements


def test_reinforcing_present_and_weighed():
    m = build(_params(), CTX)
    bars = [e for e in m.elements if e.ifc_class == "IfcReinforcingBar"]
    assert bars, "expected reinforcing elements"
    for b in bars:
        assert b.layer == "S-REBAR"
        assert b.quantities["count"] >= 1
        assert b.quantities["weight_lb"] > 0.0
        assert b.description and b.description.startswith("#")
    total = sum(b.quantities["weight_lb"] for b in bars)
    assert total > 0.0
    assert run_pre(m).passed


def test_transverse_bars_longer_under_skew():
    # Isolate the transverse-mark bars: their count is skew-invariant (spaced
    # along the slab length), so their weight rises ONLY via width/cos(skew).
    # This fails if transverse bars used plain width instead of the skewed span.
    def tran_weight(skew):
        m = build(_params(skew_deg=skew), CTX)
        return sum(e.quantities["weight_lb"] for e in m.elements
                   if e.ifc_class == "IfcReinforcingBar"
                   and ("bottom_transverse" in e.name or "top_tran" in e.name))
    w0 = tran_weight(0.0)
    w30 = tran_weight(30.0)
    assert w0 > 0.0
    # 30-deg skew stretches transverse bars by ~1/cos(30) ~ 1.1547. The fixed
    # -2*cover in the per-bar length does not scale, so the true ratio is a hair
    # above 1/cos; rel=2e-3 admits that yet still rejects the plain-width
    # mutation (which leaves w30 == w0, a ~13% miss).
    assert w30 == pytest.approx(w0 / math.cos(math.radians(30.0)), rel=2e-3)


def test_longitudinal_steel_is_skew_invariant():
    # bottom_main (#10) runs parallel to travel, spaced across the perpendicular
    # roadway width -> both count and length are skew-invariant, so its total
    # weight must not change with skew. (Fails if distributed across skew_w.)
    def main_weight(skew):
        m = build(_params(skew_deg=skew), CTX)
        return sum(e.quantities["weight_lb"] for e in m.elements
                   if e.ifc_class == "IfcReinforcingBar" and "bottom_main" in e.name)
    w0 = main_weight(0.0)
    assert w0 > 0.0
    assert main_weight(30.0) == pytest.approx(w0)


def test_dowels_follow_abutment_type():
    seat = build(_params(abutment_type="seat"), CTX)
    dia = build(_params(abutment_type="diaphragm"), CTX)
    seat_dowel = seat.element("Abut 1 approach dowels")
    dia_dowel = dia.element("Abut 1 approach dowels")
    assert (dia_dowel.quantities["weight_lb"] / dia_dowel.quantities["count"]
            > seat_dowel.quantities["weight_lb"] / seat_dowel.quantities["count"])


def test_joint_and_drainage_default_on():
    # _params() sets joint/drainage False; use a slab that omits the keys.
    p = {"alignment": ALIGN, "tables": TABLE,
         "slabs": [{"name": "A", "slab_type": "type_n_30", "station": 100.0,
                    "skew_deg": 0.0, "width_ft": 44.0}]}
    m = build(p, CTX)
    names = {e.name for e in m.elements}
    assert "A approach joint" in names
    assert "A approach drainage TPB" in names
    assert "A approach drainage pipe" in names
    assert run_pre(m).passed


def test_joint_off_drainage_on():
    m = build(_params(joint=False, drainage=True), CTX)
    names = {e.name for e in m.elements}
    assert "Abut 1 approach joint" not in names
    assert "Abut 1 approach drainage TPB" in names


def test_joint_and_pipe_length_follow_skew():
    # joint + slotted pipe run along the skewed abutment edge -> width/cos(skew).
    # (Fails if they used plain width.)
    m = build(_params(joint=True, drainage=True, skew_deg=30.0), CTX)
    expect = 44.0 / math.cos(math.radians(30.0))
    jt = m.element("Abut 1 approach joint")
    pipe = m.element("Abut 1 approach drainage pipe")
    assert jt.quantities["length_ft"] == pytest.approx(expect, rel=1e-6)
    assert pipe.quantities["length_ft"] == pytest.approx(expect, rel=1e-6)
    assert jt.ifc_class != "IfcSlab"


def test_drainage_tpb_area_matches_footprint():
    m = build(_params(joint=False, drainage=True), CTX)
    tpb = m.element("Abut 1 approach drainage TPB")
    assert tpb.quantities["area_sf"] == pytest.approx(30.0 * 44.0)
    assert tpb.ifc_class != "IfcSlab"


def test_length_vs_type_key_check_fails_on_mismatch():
    bad_table = {"type_n_30": {**TABLE["type_n_30"], "length_ft": 10.0}}  # 10 on a _30 row
    p = {"alignment": ALIGN, "tables": bad_table,
         "slabs": [{"name": "A", "slab_type": "type_n_30", "station": 100.0,
                    "width_ft": 44.0, "joint": False, "drainage": False}]}
    rep = run_pre(build(p, CTX))
    assert not rep.passed
    assert any("type key" in f.lower() for f in rep.failures)


def test_pay_isolation_check_passes_on_clean_model():
    m = build(_params(joint=True, drainage=True), CTX)
    slabs = [e for e in m.elements if e.ifc_class == "IfcSlab"]
    assert len(slabs) == 1                       # only the slab prism
    assert run_pre(m).passed


def test_only_one_ifcslab_per_slab():
    p = {"alignment": ALIGN, "tables": TABLE,
         "slabs": [{"name": "A", "slab_type": "type_n_30", "station": 100.0,
                    "width_ft": 44.0, "joint": True, "drainage": True},
                   {"name": "B", "slab_type": "type_eq_10", "station": 300.0,
                    "width_ft": 40.0, "joint": True, "drainage": True}]}
    m = build(p, CTX)
    assert sum(1 for e in m.elements if e.ifc_class == "IfcSlab") == 2
    assert run_pre(m).passed


def test_pay_isolation_check_fires_on_stray_ifcslab():
    # A non-slab element mislabeled into the IfcSlab concrete pay class must
    # trip the pay-isolation gate. (Guards _check_pay_isolation against being
    # silently broken -- without this, the check could return [] and every
    # other test would still pass.)
    m = build(_params(joint=False, drainage=False), CTX)
    m.add(Element("bogus curb", "IfcSlab", quantities={}))
    rep = run_pre(m)
    assert not rep.passed
    assert any("pay" in f.lower() for f in rep.failures)


def test_registered_in_family_registry():
    from bimforge.author.families.registry import available
    assert "approach-slab" in available()


def test_multi_type_concrete_routes_per_type():
    # The whole point of the type-encoded slab name: a mixed N+EQ model must
    # route its two concrete slabs to DISTINCT per-type pay codes off the
    # SHIPPED paycodes file (guards against a single-code regression).
    from pathlib import Path
    from bimforge.author import paycodes as pc_mod
    shipped = (Path(__file__).resolve().parent.parent / "examples"
               / "caltrans-b9-approach-slab.paycodes.yaml")
    p = {"alignment": ALIGN, "tables": TABLE,
         "slabs": [{"name": "A", "slab_type": "type_n_30", "station": 100.0,
                    "width_ft": 44.0, "joint": False, "drainage": False},
                   {"name": "B", "slab_type": "type_eq_10", "station": 300.0,
                    "width_ft": 40.0, "joint": False, "drainage": False}]}
    m = build(p, CTX)
    pc = pc_mod.load(str(shipped))
    pc_mod.apply(m, pc)
    n_slab = m.element("A approach slab type_n_30")
    eq_slab = m.element("B approach slab type_eq_10")
    assert n_slab.classifications == ["STRUCT-CONC-AS-N"]
    assert eq_slab.classifications == ["STRUCT-CONC-AS-EQ"]
    assert n_slab.classifications != eq_slab.classifications


def test_build_from_spec_end_to_end(tmp_path):
    import shutil
    from pathlib import Path
    import yaml
    from bimforge.author.families.registry import build_from_spec
    tables = {"type_n_30": TABLE["type_n_30"]}
    (tmp_path / "tables.yaml").write_text(yaml.safe_dump(tables), encoding="utf-8")
    # Exercise the SHIPPED example paycodes end-to-end (not an inline dict), so
    # a mis-keyed shipped file cannot ship green.
    examples = Path(__file__).resolve().parent.parent / "examples"
    shutil.copy(examples / "caltrans-b9-approach-slab.paycodes.yaml",
                tmp_path / "paycodes.yaml")
    spec = {
        "family": "approach-slab",
        "params": {
            "alignment": ALIGN,
            "tables_file": "tables.yaml",
            "slabs": [{"name": "Abut 1", "slab_type": "type_n_30",
                       "station": 100.0, "skew_deg": 20.0, "width_ft": 44.0,
                       "abutment_type": "seat"}],
        },
        "paycodes": "paycodes.yaml",
        "outputs": {"dxf": "out.dxf", "ifc": "out.ifc",
                    "takeoff_map": "out-takeoff-map.yaml", "ifc_allow_local": True},
        "project": {"name": "b9smoke", "guid_ns": "00000000-0000-0000-0000-000000000009"},
    }
    (tmp_path / "spec.yaml").write_text(yaml.safe_dump(spec), encoding="utf-8")
    rc = build_from_spec(tmp_path / "spec.yaml")
    assert rc == 0
    assert (tmp_path / "out.dxf").exists()
    assert (tmp_path / "out.ifc").exists()
    assert (tmp_path / "out-takeoff-map.yaml").exists()
    # Assert the takeoff map carries the SHIPPED file's pay codes with the
    # right units -- an empty/mis-keyed map would slip past a bare exists().
    tmap = yaml.safe_load((tmp_path / "out-takeoff-map.yaml").read_text(encoding="utf-8"))
    codes = tmap["codes"]
    assert codes["STRUCT-CONC-AS-N"]["unit"] == "CY"
    assert codes["BAR-STEEL-AS"]["unit"] == "LB"
