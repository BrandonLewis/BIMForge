import json

import ifcopenshell
import ifcopenshell.api.classification
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit

from bimforge.bim import cli


def _pile_ifc(path):
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=pile,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"Length": 12_500.0})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    ifcopenshell.api.classification.add_reference(
        f, products=[pile], identification="PILE-200W-FRN", name="",
        classification=system)
    f.write(str(path))


def _write_inputs(tmp_path):
    tmap = tmp_path / "map.yaml"
    tmap.write_text(
        "project_ref: B9\n"
        "codes:\n"
        "  PILE-200W-FRN:\n"
        "    measure: Length\n"
        "    unit: LF\n"
        "    item_number: '0055'\n", encoding="utf-8")
    costs = tmp_path / "c.json"
    costs.write_text(json.dumps(
        {"PILE-200W-FRN": {"cost": 500.0, "labor_hours": None,
                           "unit_price": 10.0, "unit": "LF"}}),
        encoding="utf-8")
    return tmap, costs


def test_cli_estimate5d_writes_est_ifc_and_prints_variance(tmp_path, capsys):
    ifc = tmp_path / "m.ifc"
    _pile_ifc(ifc)
    tmap, costs = _write_inputs(tmp_path)
    rc = cli.main(["estimate5d", "--ifc", str(ifc), "--map", str(tmap),
                   "--costs", str(costs)])
    assert rc == 0
    out_path = tmp_path / "m.est.ifc"
    assert out_path.exists()                      # default: <stem>.est.ifc
    model = ifcopenshell.open(str(out_path))
    (cs,) = model.by_type("IfcCostSchedule")
    assert cs.PredefinedType == "ESTIMATE"
    out = capsys.readouterr().out
    assert "extended" in out.lower()
    assert "vs BM" in out                         # the variance line


def test_cli_estimate5d_bad_inputs_are_one_line_errors(tmp_path, capsys):
    ifc = tmp_path / "m.ifc"
    _pile_ifc(ifc)
    tmap, costs = _write_inputs(tmp_path)
    # unknown measure in the map -> error: + rc 1, no traceback
    tmap.write_text("codes:\n  X:\n    measure: Bogus\n", encoding="utf-8")
    rc = cli.main(["estimate5d", "--ifc", str(ifc), "--map", str(tmap),
                   "--costs", str(costs)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
    # unreadable IFC
    bad = tmp_path / "bad.ifc"
    bad.write_text("not an ifc", encoding="utf-8")
    _, costs2 = _write_inputs(tmp_path)
    tmap.write_text("codes: {}\n", encoding="utf-8")
    rc = cli.main(["estimate5d", "--ifc", str(bad), "--map", str(tmap),
                   "--costs", str(costs2)])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_estimate5d_warns_on_a_lump_sum_over_zero_counts(tmp_path, capsys):
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for i in range(2):
        el = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcBuildingElementProxy", name=f"Temp signal {i}")
        qto = ifcopenshell.api.pset.add_qto(f, product=el,
                                            name="Qto_BaseQuantities")
        ifcopenshell.api.pset.edit_qto(f, qto=qto, properties={"Count": 0})
        ifcopenshell.api.classification.add_reference(
            f, products=[el], identification="SIG", name="",
            classification=system)
    ifc = tmp_path / "sig.ifc"
    f.write(str(ifc))
    tmap = tmp_path / "map.yaml"
    tmap.write_text("codes:\n  SIG:\n    measure: Count\n    unit: LS\n",
                    encoding="utf-8")
    costs = tmp_path / "c.json"
    costs.write_text(json.dumps(
        {"SIG": {"cost": 50000.0, "unit_price": 50000.0, "unit": "LS"}}),
        encoding="utf-8")
    rc = cli.main(["estimate5d", "--ifc", str(ifc), "--map", str(tmap),
                   "--costs", str(costs)])
    assert rc == 0
    err = capsys.readouterr().err
    assert ("SIG: its elements' Count sums to 0, so a lump sum / count_as "
            "of 1 cannot be priced off them -- extended $0") in err
