from pathlib import Path
import yaml
import pytest

CAT = (Path(__file__).resolve().parents[1] / "data" / "caltrans-2025"
       / "tables" / "caltrans-d90-headwall.yaml")


@pytest.mark.skipif(not CAT.exists(), reason="real D90 catalog not built")
def test_d90_catalog_fixed_rules_present():
    d90 = yaml.safe_load(CAT.read_text())["d90"]

    # Wingwall types A/B/C: A/B straight, C is a wall; Type C requires a barrier.
    wt = d90["wingwall_types"]
    assert set(wt) >= {"A", "B", "C"}
    assert wt["A"]["shape"] == "straight" and wt["B"]["shape"] == "straight"
    assert wt["C"]["shape"] == "wall"
    assert wt["C"]["barrier"] == "required"
    assert wt["A"]["barrier"] == "none"
    for t in ("A", "B", "C"):
        assert wt[t]["b3_plans"], t   # each references B3 Type-1 standard plans

    # Pipe distribution reinforcing is RC-only; metal pipe uses hook bolts.
    pipe = d90["pipe"]
    assert pipe["distribution"]["material"] == "rc_only"
    assert 6 in pipe["distribution"]["sizes"]
    assert pipe["metal"] == "hook_bolts"

    # Type C barrier is Caltrans Type 836 (36in = 3.0 ft) per B11-80.
    tcb = d90["type_c_barrier"]
    assert tcb["barrier_type"] == "836"
    assert tcb["h_ft"] == pytest.approx(3.0)

    # Design material properties transcribed from the sheet.
    dz = d90["design"]
    assert dz["fc_psi"] == 3600 and dz["fy_psi"] == 60000
    assert dz["soil_unit_weight_pcf"] == 120 and dz["soil_phi_deg"] == 34
