import json
import ifcopenshell
import ifcopenshell.api.root as root
import ifcopenshell.api.sequence as sq
from bimforge.bim import cli


def _make_4d_ifc(path):
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject")
    ws = sq.add_work_schedule(f, name="S")
    sq.add_task(f, work_schedule=ws, name="Pour", identification="1")
    f.write(str(path))


def test_cli_cost5d_writes_enriched_ifc(tmp_path, capsys):
    ifc = tmp_path / "m.4d.ifc"
    _make_4d_ifc(ifc)
    sched = tmp_path / "s.json"
    sched.write_text(json.dumps({"name": "S", "tasks": [
        {"id": "t1", "name": "Pour", "wbs": "1", "start": "2026-08-10",
         "finish": "2026-08-14", "bid_item_codes": ["A"]}]}), encoding="utf-8")
    costs = tmp_path / "c.json"
    costs.write_text(json.dumps({"A": {"cost": 10000.0, "labor_hours": 400.0}}),
                     encoding="utf-8")
    out = tmp_path / "m.5d.ifc"
    rc = cli.main(["cost5d", "--ifc", str(ifc), "--schedule", str(sched),
                   "--costs", str(costs), "--out", str(out)])
    assert rc == 0
    model = ifcopenshell.open(str(out))
    assert model.by_type("IfcCostSchedule") and model.by_type("IfcLaborResource")
    assert "cost items" in capsys.readouterr().out.lower()
