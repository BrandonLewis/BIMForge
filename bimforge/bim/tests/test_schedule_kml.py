"""KML TimeSpan staging from an embedded schedule (4D staging slice 3)."""
import re

import pytest

ezdxf = pytest.importorskip("ezdxf")
shapely = pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")
yaml = pytest.importorskip("yaml")

from importlib.resources import files  # noqa: E402

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.kml import ifc_to_kml  # noqa: E402
from bimforge.bim.sample import write_sample_dxf  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.schedule_read import element_start_dates  # noqa: E402
from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask  # noqa: E402


def _example(name):
    return yaml.safe_load(
        (files("bimforge.bim") / "examples" / name).read_text())


@pytest.fixture(scope="module")
def scheduled_ifc(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("kml4d")
    dxf = write_sample_dxf(str(tmp / "s.dxf"))
    lm = _example("layer_map.example.yaml")
    feats = extract_features(dxf, lm["layers"], UNIT_TO_M[lm["units"]["dxf_length_unit"]])
    ifc = str(tmp / "m.ifc")
    build_ifc(feats, lm, ifc)
    sched = CanonicalSchedule(name="Stg", tasks=[
        ScheduleTask(id="deck", name="Deck", wbs="1",
                     start="2026-07-10", finish="2026-07-14",
                     bid_item_codes=["03 30 00"]),          # -> IfcSlab
        ScheduleTask(id="cols", name="Columns", wbs="2",
                     start="2026-07-20", finish="2026-07-22",
                     bid_item_codes=["05 12 00"]),          # -> 4 IfcColumns
    ])
    model = ifcopenshell.open(ifc)
    embed_schedule(model, sched)
    scheduled = str(tmp / "m4d.ifc")
    model.write(scheduled)
    return tmp, scheduled


def test_element_start_dates_earliest_per_element(scheduled_ifc):
    _, ifc = scheduled_ifc
    model = ifcopenshell.open(ifc)
    starts = element_start_dates(model)
    slab = model.by_type("IfcSlab")[0]
    cols = model.by_type("IfcColumn")
    assert starts[slab.id()] == "2026-07-10"
    assert all(starts[c.id()] == "2026-07-20" for c in cols)
    # curb/hatch/wall are unscheduled -> absent
    assert model.by_type("IfcWall")[0].id() not in starts


def test_kml_schedule_stamps_timespans(scheduled_ifc):
    tmp, ifc = scheduled_ifc
    out = tmp / "staged.kml"
    info = ifc_to_kml(ifc, str(out), schedule=True)
    assert info["timed"] == 5                      # 1 slab + 4 columns
    text = out.read_text(encoding="utf-8")
    assert "<TimeSpan><begin>2026-07-10</begin></TimeSpan>" in text
    assert "<TimeSpan><begin>2026-07-20</begin></TimeSpan>" in text
    # exactly the scheduled elements are timed
    assert len(re.findall(r"<TimeSpan>", text)) == 5


def test_kml_without_schedule_flag_has_no_timespans(scheduled_ifc):
    tmp, ifc = scheduled_ifc
    out = tmp / "plain.kml"
    info = ifc_to_kml(ifc, str(out))               # schedule=False default
    assert info["timed"] == 0
    assert "<TimeSpan>" not in out.read_text(encoding="utf-8")


def test_kml_schedule_on_unscheduled_ifc_reports_zero(scheduled_ifc, tmp_path):
    # An IFC with no embedded schedule: schedule=True yields timed=0, no crash.
    tmp, _ = scheduled_ifc
    plain = str(tmp / "m.ifc")                      # the pre-embed model
    info = ifc_to_kml(plain, str(tmp_path / "z.kml"), schedule=True)
    assert info["timed"] == 0


def test_cli_kml_schedule_end_to_end(scheduled_ifc, tmp_path, capsys):
    from bimforge.bim.cli import main

    _, ifc = scheduled_ifc
    out = tmp_path / "cli.kml"
    rc = main(["kml", ifc, "--out", str(out), "--schedule"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "5 element(s) carry a construction TimeSpan" in printed
    assert "<TimeSpan>" in out.read_text(encoding="utf-8")


def test_kml_massing_emits_box_faces_and_shrinks(scheduled_ifc):
    tmp, ifc = scheduled_ifc
    full = tmp / "full.kml"
    box = tmp / "box.kml"
    fi = ifc_to_kml(ifc, str(full))
    bi = ifc_to_kml(ifc, str(box), massing=True)
    assert bi["elements"] == fi["elements"]        # same elements, coarser geometry
    bt = box.read_text(encoding="utf-8")
    ft = full.read_text(encoding="utf-8")
    # every element -> exactly 6 box faces
    assert bt.count("<Polygon>") == 6 * bi["elements"]
    # massing is coarser: the full mesh emits at least as many polygons
    # (stable regardless of file byte size)
    assert ft.count("<Polygon>") >= bt.count("<Polygon>")


def test_kml_massing_with_schedule_keeps_timespans(scheduled_ifc):
    tmp, ifc = scheduled_ifc
    out = tmp / "staged_box.kml"
    info = ifc_to_kml(ifc, str(out), schedule=True, massing=True)
    assert info["timed"] == 5
    assert "<TimeSpan><begin>2026-07-10</begin></TimeSpan>" in out.read_text(encoding="utf-8")


def test_box_rings_empty_geometry_returns_no_rings():
    from bimforge.bim.kml import _box_rings
    assert _box_rings([], lambda x, y: (0.0, 0.0)) == []
