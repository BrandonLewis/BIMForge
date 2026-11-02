"""ifc2gis: 4D dates and stationing on every GIS feature (QGIS-ready)."""
from __future__ import annotations

import sqlite3

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402

from bimforge.author.tests.test_emit_alignment import _emit, _model  # noqa: E402
from bimforge.bim.ifc2gis import ifc_to_gpkg  # noqa: E402


def test_features_carry_dates_and_stations(tmp_path):
    m, al, prof = _model()
    path, f = _emit(tmp_path, m)
    run = ifcopenshell.api.run
    ws = run("sequence.add_work_schedule", f, name="baseline")
    t = run("sequence.add_task", f, work_schedule=ws, name="Deck pour")
    t.PredefinedType = "CONSTRUCTION"
    tt = run("sequence.add_task_time", f, task=t)
    run("sequence.edit_task_time", f, task_time=tt,
        attributes={"ScheduleStart": "2027-09-15T08:00:00"})
    (deck,) = [p for p in f.by_type("IfcSlab") if p.Name == "deck"]
    run("sequence.assign_product", f, relating_product=deck, related_object=t)
    f.write(str(path))
    out = tmp_path / "m.gpkg"
    ifc_to_gpkg([str(path)], str(out))
    con = sqlite3.connect(str(out))
    (table,) = [r[0] for r in con.execute(
        "select table_name from gpkg_geometry_columns "
        "where geometry_type_name = 'MULTIPOLYGON'")]
    types = {r[1]: r[2] for r in con.execute(f'pragma table_info("{table}")')}
    assert types["appear_date"] == "DATE" and types["vanish_date"] == "DATE"
    row = con.execute(f'select appear_date, vanish_date, alignment, sta_from, '
                      f'sta_to, sta_from_txt, off_from, off_to from "{table}" '
                      f'where name = "deck"').fetchone()
    appear, vanish, aname, s0, s1, s0txt, o0, o1 = row
    assert (appear, vanish, aname) == ("2027-09-15", None, "ML")
    # the deck is swept 1010..1360 ft, 6 ft each side of the line
    assert s0 == pytest.approx(1010.0, abs=0.05)
    assert s1 == pytest.approx(1360.0, abs=0.05)
    assert s0txt == "10+10.00"
    # +/-6 ft section; ifcopenshell draws the exact alignment sweep with a
    # few vertices a little wide near the reverse curve (IfcOpenShell#9820,
    # which the gate also works around) - the GIS reads what is drawn
    assert o0 == pytest.approx(-6.0, abs=0.25) and o1 == pytest.approx(6.0, abs=0.25)
