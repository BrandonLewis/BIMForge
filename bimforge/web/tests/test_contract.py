"""bimforge.web.contract: the bundle behind the pages."""
from __future__ import annotations

import json
import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.paycodes import apply as pc_apply, from_dict  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.bim import cost5d  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask  # noqa: E402
from bimforge.web import CONTRACT, build_bundle, validate_bundle, write_site  # noqa: E402
from bimforge.web.contract import dump_bundle  # noqa: E402

PC = from_dict({
    "rules": [{"match": "(?i)footing", "group": "ftg"},
              {"match": "(?i)wall", "group": "wall"},
              {"match": "(?i)post", "group": "post"}],
    "groups": {"ftg": {"measure": "GrossVolume"},
               "wall": {"measure": "GrossVolume"},
               "post": {"measure": "Count"}},
    "codes": {"F-CONC": {"group": "ftg", "measure": "GrossVolume", "unit": "CY",
                         "item_number": "0010", "description": "Footing concrete"},
              "W-CONC": {"group": "wall", "measure": "GrossVolume", "unit": "CY",
                         "item_number": "0020", "description": "Wall concrete"},
              "POSTS": {"group": "post", "measure": "Count", "unit": "EA",
                        "item_number": "0030", "description": "Posts"}},
})
TMAP = {"organization_id": 7, "project_ref": "web-fixture",
        "codes": {"F-CONC": {"measure": "GrossVolume", "unit": "CY",
                             "item_number": "0010",
                             "description": "Footing concrete"},
                  "W-CONC": {"measure": "GrossVolume", "unit": "CY",
                             "item_number": "0020",
                             "description": "Wall concrete"},
                  "POSTS": {"measure": "Count", "unit": "EA",
                            "item_number": "0030", "description": "Posts"}}}
OFFICIAL = {"0010": {"quantity": 50.0, "description": "Footing concrete",
                     "unit": "CY"},
            "0020": {"quantity": 30.0, "description": "Wall concrete",
                     "unit": "CY"}}
COSTS = {"F-CONC": {"cost": 12000.0, "labor_hours": 300.0},
         "W-CONC": {"cost": 9000.0, "labor_hours": 200.0},
         "POSTS": {"cost": 1500.0, "labor_hours": 40.0}}


def _model():
    ctx = ProjectContext(name="Web Fixture", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=8080))
    m = StructureModel("web", ctx)
    for i, x in enumerate((0.0, 40.0), start=1):
        p = Prism(f"Abut {i} footing", [(-5, -10), (5, -10), (5, 10), (-5, 10)],
                  z_bot=0.0, z_top=3.0, ifc="IfcFooting")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x,
                                    material="Concrete"))
        w = Prism(f"Abut {i} wall", [(-1.5, -10), (1.5, -10), (1.5, 10), (-1.5, 10)],
                  z_bot=3.0, z_top=15.0, ifc="IfcWall")
        m.add(Element.from_geometry(w.name, w, ifc_class="IfcWall", x_ft=x,
                                    material="Concrete", type_name="Stem wall"))
    m.add(Element("Rail run", "IfcRailing", predefined_type="HANDRAIL",
                  type_name="Rail"))
    for i in range(3):
        p = Prism(f"Rail post {i + 1}", [(-0.1 + 10 * i, 10), (0.1 + 10 * i, 10),
                                         (0.1 + 10 * i, 10.2), (-0.1 + 10 * i, 10.2)],
                  z_bot=15.0, z_top=16.4, ifc="IfcMember")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcMember",
                                    predefined_type="POST", type_name="Post",
                                    part_of="Rail run",
                                    quantities={"count": 1}))
    m.add(Element("Existing ground", "IfcGeographicElement",
                  predefined_type="TERRAIN", classifications=[],
                  geometry={"kind": "mesh", "units": "ft",
                            "verts": [(0, 0, -1), (50, 0, -1), (0, 30, -1.5),
                                      (50, 30, -1.5)],
                            "tris": [(0, 1, 2), (1, 3, 2)]}))
    pc_apply(m, PC)
    return m


def _schedule():
    return CanonicalSchedule(name="Stage 1", start_date="2027-03-01", tasks=[
        ScheduleTask(id="t1", name="Footings", wbs="1", start="2027-03-01",
                     finish="2027-03-12", match_ifc_class="IfcFooting",
                     bid_item_codes=["F-CONC"]),
        ScheduleTask(id="t2", name="Walls", wbs="2", start="2027-03-15",
                     finish="2027-04-09", match_name_re="wall$",
                     bid_item_codes=["W-CONC"]),
        ScheduleTask(id="t3", name="Rail", wbs="3", start="2027-04-12",
                     finish="2027-04-16", match_ifc_class="IfcMember",
                     bid_item_codes=["POSTS"]),
        ScheduleTask(id="t4", name="Open to traffic", wbs="4",
                     start="2027-04-30", finish="2027-04-30",
                     is_milestone=True),
    ])


def _ifc(tmp_path, with_4d=True, with_5d=True):
    out = tmp_path / "web.ifc"
    emit_ifc(_model(), str(out), PC)
    if with_4d:
        f = ifcopenshell.open(str(out))
        embed_schedule(f, _schedule())
        if with_5d:
            cost5d.embed_cost_and_resources(f, _schedule(), COSTS,
                                            schedule_name="Stage 1")
        f.write(str(out))
    return out


def test_bundle_shape_and_links(tmp_path):
    ifc = _ifc(tmp_path)
    b = build_bundle(ifc, TMAP, OFFICIAL)
    assert b["contract"] == CONTRACT
    assert b["model"]["file"] == "web.ifc"
    assert b["model"]["schema"].startswith("IFC4X3")
    assert b["model"]["project"] == "Web Fixture"
    els = b["elements"]
    posts = [e for e in els.values() if e["name"].startswith("Rail post")]
    assert len(posts) == 3
    run = next(e for e in els.values() if e["name"] == "Rail run")
    assert run["predefined_type"] == "HANDRAIL" and run["type"] == "Rail"
    assert all(p["whole"] == next(g for g, e in els.items() if e is run)
               for p in posts)
    assert len(run["parts"]) == 3
    assert posts[0]["predefined_type"] == "POST"      # through the type
    ftg = next(e for e in els.values() if e["name"] == "Abut 1 footing")
    assert ftg["codes"] == ["F-CONC"]
    assert ftg["qto"]["GrossVolume"] == pytest.approx(          # 10 x 20 x 3
        600 * (0.3048006096 ** 3), rel=1e-6)
    assert ftg["appear"] == "2027-03-01" and ftg["vanish"] is None
    assert ftg["tasks"] == ["Footings"]
    # takeoff rows carry per-element quantities in the row's unit and the
    # official quantity with its variance
    rows = {r["cost_code"]: r for r in b["takeoff"]["rows"]}
    assert set(rows) == {"F-CONC", "W-CONC", "POSTS"}
    f = rows["F-CONC"]
    assert f["unit"] == "CY" and f["item_number"] == "0010"
    assert f["quantity"] == pytest.approx(2 * 600 / 27.0, rel=1e-4)   # survey ft -> CY
    assert f["official_quantity"] == 50.0
    assert f["variance"] == pytest.approx(f["quantity"] - 50.0)
    assert f["variance_pct"] == pytest.approx(100 * f["variance"] / 50.0, abs=0.01)
    assert sum(e["quantity"] for e in f["elements"]) == pytest.approx(
        f["quantity"], abs=1e-3)                     # each rounded to 4 dp
    assert rows["POSTS"]["quantity"] == 3
    assert rows["POSTS"]["official_quantity"] is None
    assert rows["POSTS"]["variance"] is None
    ground = next(g for g, e in els.items() if e["name"] == "Existing ground")
    assert b["takeoff"]["unclassified"] == [ground]
    # schedule and its element links
    s = b["schedule"]
    assert s["name"] == "Stage 1"
    assert [t["id"] for t in s["tasks"]] == ["t1", "t2", "t3", "t4"]
    assert s["tasks"][3]["is_milestone"] is True
    assert len(s["task_elements"]["t1"]) == 2
    assert len(s["task_elements"]["t3"]) == 3
    assert s["task_elements"].get("t4", []) == []
    # costs by task
    c = b["costs"]
    assert c["tasks"]["t1"]["cost"] == pytest.approx(12000.0)
    assert c["tasks"]["t1"]["labor_hours"] == pytest.approx(300.0)
    assert set(c["costs"]) == {"F-CONC", "W-CONC", "POSTS"}


def test_bundle_without_4d_or_5d(tmp_path):
    ifc = _ifc(tmp_path, with_4d=False)
    b = build_bundle(ifc, TMAP)
    assert b["schedule"] is None and b["costs"] is None
    assert all(e["appear"] is None for e in b["elements"].values())
    assert b["takeoff"]["rows"][0]["official_quantity"] is None
    ifc4d = _ifc(tmp_path, with_5d=False)
    b = build_bundle(ifc4d, TMAP)
    assert b["schedule"] is not None and b["costs"] is None


def test_bundle_without_a_map_uses_natural_units(tmp_path):
    ifc = _ifc(tmp_path, with_4d=False)
    b = build_bundle(ifc)
    rows = {r["cost_code"]: r for r in b["takeoff"]["rows"]}
    assert rows["F-CONC"]["unit"]                    # a natural unit
    assert rows["F-CONC"]["item_number"] is None
    assert rows["F-CONC"]["official_quantity"] is None
    assert any("no map entry" in w for w in b["takeoff"]["warnings"])


def test_bundle_is_deterministic_and_validates(tmp_path):
    # (one file read twice: the schedule embed mints its own task GlobalIds,
    # so two embeds are two files; the bundle of ONE file never moves)
    ifc = _ifc(tmp_path)
    a = dump_bundle(build_bundle(ifc, TMAP, OFFICIAL))
    b = dump_bundle(build_bundle(ifc, TMAP, OFFICIAL))
    assert a == b
    assert "generated" not in a and "timestamp" not in a
    doc = json.loads(a)
    validate_bundle(doc)
    doc["contract"] = "bimforge-web/2"
    with pytest.raises(ValueError, match="not a bimforge-web/1"):
        validate_bundle(doc)
    doc = json.loads(a)
    doc["takeoff"]["rows"][0]["elements"][0]["global_id"] = "nope"
    with pytest.raises(ValueError, match="lacks"):
        validate_bundle(doc)


def test_write_site_lays_out_pages_and_bundle(tmp_path):
    b = build_bundle(_ifc(tmp_path), TMAP, OFFICIAL)
    index = write_site(b, tmp_path / "site")
    site = tmp_path / "site"
    assert index == site / "index.html"
    for page in ("index.html", "takeoff.html", "dashboard.html"):
        text = (site / page).read_text(encoding="utf-8")
        assert "data/bundle.js" in text and "assets/shared.js" in text
    for asset in ("app.css", "shared.js", "takeoff.js", "dashboard.js"):
        assert (site / "assets" / asset).exists()
    js = (site / "data" / "bundle.js").read_text(encoding="utf-8")
    assert js.startswith("// generated by bimforge")
    assert "window.BIMFORGE_BUNDLE = {" in js
    again = json.loads((site / "data" / "bundle.json").read_text(encoding="utf-8"))
    assert again == b
    # the JS payload is the JSON payload
    assert js.split("= ", 1)[1].rstrip().rstrip(";") == \
        (site / "data" / "bundle.json").read_text(encoding="utf-8").rstrip()


def test_cli_web_writes_a_site(tmp_path, capsys):
    import yaml

    from bimforge.bim.cli import main
    ifc = _ifc(tmp_path)
    tmap = tmp_path / "map.yaml"
    tmap.write_text(yaml.safe_dump(TMAP), encoding="utf-8")
    official = tmp_path / "bid.json"
    official.write_text(json.dumps([{"item_number": "0010", "quantity": 50.0}]),
                        encoding="utf-8")
    out = tmp_path / "site"
    rc = main(["web", "--ifc", str(ifc), "--map", str(tmap),
               "--official", str(official), "--out", str(out)])
    assert rc == 0
    assert (out / "dashboard.html").exists()
    doc = json.loads((out / "data" / "bundle.json").read_text(encoding="utf-8"))
    assert doc["takeoff"]["rows"][0]["official_quantity"] == 50.0
    printed = capsys.readouterr().out
    assert "site written" in printed and "3 pay items" in printed
