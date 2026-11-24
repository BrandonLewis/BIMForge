"""The V1.1 road corridor builds as it did before the path (P.6, part C).

fixtures/road-corridor-v11/ holds the shipped example as V1.1 shipped it,
its spec and paycodes copied before part C changed the example, and what it
built then: every element's and root's GlobalId, every element's
Qto_BaseQuantities GrossVolume, and the mass-haul, walls, structures and
guardrail tables. Every part C key is optional: without `path` the corridor
builds the same elements, GlobalIds, quantities and tables. The only change
is two new columns, `location` in the walls table and `carries` in the
structures table, which are dropped before comparing.

The earthwork volumes and the mass haul were re-recorded when the earthwork
columns began following the leaning section rays (corridor.earthwork) in
place of standing vertically over plan triangles: each band's volume rose
0.024 to 0.156 %, 0.09 % in all. Nothing else moved.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

FIXTURE = Path(__file__).parent / "fixtures" / "road-corridor-v11"
SPEC = "road-corridor.spec.yaml"


def _recorded(name: str):
    return json.loads((FIXTURE / name).read_text("utf-8"))


def _rows(text: str, drop: str | None = None) -> list:
    """The CSV's rows, the column `drop` taken out where it is there."""
    rows = list(csv.reader(io.StringIO(text)))
    if drop is not None and drop in rows[0]:
        k = rows[0].index(drop)
        rows = [r[:k] + r[k + 1:] for r in rows]
    return rows


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("v11")
    for name in (SPEC, "road-corridor.paycodes.yaml"):
        shutil.copy(FIXTURE / name, tmp / name)
    with contextlib.redirect_stderr(io.StringIO()):
        assert build_from_spec(str(tmp / SPEC)) == 0
    return ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc")), tmp / "out"


def test_every_v11_element_keeps_its_globalid(built):
    f, _out = built
    was = _recorded("globalids.json")["elements"]
    now = {el.Name: el.GlobalId for el in f.by_type("IfcElement")}
    assert now == was                             # none moved, none added


def test_every_v11_root_keeps_its_globalid(built):
    f, _out = built
    moved = {}
    for gid, cls in _recorded("globalids.json")["roots"].items():
        try:
            ent = f.by_guid(gid)
        except RuntimeError:
            moved[gid] = (cls, None)
            continue
        if ent.is_a() != cls:
            moved[gid] = (cls, ent.is_a())
    assert not moved, f"{len(moved)} V1.1 root(s) moved or dropped: {moved}"


def test_every_v11_volume_is_unchanged(built):
    import ifcopenshell.util.element as E
    f, _out = built
    now = {}
    for el in f.by_type("IfcElement"):
        base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
        if "GrossVolume" in base:
            now[el.Name] = base["GrossVolume"]
    was = _recorded("volumes.json")
    assert set(now) == set(was)
    for name, v in was.items():
        assert now[name] == pytest.approx(v, rel=1e-9), name


@pytest.mark.parametrize("key, drop", [("masshaul", None), ("guardrail", None),
                                       ("walls", "location"),
                                       ("structures", "carries")])
def test_every_v11_table_is_unchanged(built, key, drop):
    _f, out = built
    now = (out / f"road-corridor.{key}.csv").read_text("utf-8")
    was = (FIXTURE / f"{key}.csv").read_text("utf-8")
    assert _rows(now, drop) == _rows(was, drop)


# -- on a 7 % grade: earthwork columns follow the leaning section rays --------

def _steep_spec(tmp, case):
    """The fixture's spec on a straight 7 % grade with no widening and walls
    up to 40 ft. "listed": no automatic walls, the ground at 260, the
    listed left wall at 22+00 to 23+00 standing on fill; "cut": the ground
    at 380 and the listed wall dropped, so automatic cut walls take over.
    A section's points lean 0.07 ft back per ft up, so on a wall's 1 ft
    lead-in the wall's top and toe sit feet apart along the line."""
    import yaml
    spec = yaml.safe_load((FIXTURE / SPEC).read_text("utf-8"))
    p = spec["params"]
    s0, s1, g = 1000.0, 2549.07, 7.0
    p["profile"] = {"curves": [{"bvc_station": s0, "bvc_elev": 298.0,
                                "g_in_pct": g, "g_out_pct": g,
                                "length_ft": s1 - s0, "evc_station": s1,
                                "evc_elev": round(298.0 + g / 100.0 * (s1 - s0), 5)}]}
    p.pop("widths")
    p["max_wall_height_ft"] = 40.0
    if case == "listed":
        assert [(g["from"], g["to"]) for g in p["gaps"]
                if g["kind"] == "wall"] == [(2200, 2300)]
        p.pop("walls")
        p["ground"]["elevation"] = 260.0
        p["section"]["side_slopes"]["footprint_ft"] = {"L": 1000, "R": 1000}
        p["section"]["side_slopes"]["daylight_limit_ft"] = 1000
        for key in ("walls", "structures"):
            spec["outputs"].pop(key)
    else:
        p["ground"]["elevation"] = 380.0
        p["gaps"] = [gap for gap in p["gaps"] if gap["kind"] != "wall"]
    shutil.copy(FIXTURE / "road-corridor.paycodes.yaml", tmp)
    (tmp / SPEC).write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    return tmp / SPEC


@pytest.mark.parametrize("case", ["listed", "cut"])
def test_a_wall_s_lead_in_on_a_steep_grade_passes_the_gate(tmp_path, case):
    # columns stood vertically over plan triangles folded on the lead-in:
    # the listed fill wall's band came out 54 % off the post gate, the cut
    # wall's 0.51 %
    from bimforge.author.families.registry import build_from_spec
    path = _steep_spec(tmp_path, case)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre gate and the post gate both passed
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    out = tmp_path / "out"
    if case == "cut":
        # an automatic cut wall ending inside the alignment, so with a lead-in
        rows = list(csv.DictReader(io.StringIO(
            (out / "road-corridor.walls.csv").read_text("utf-8"))))
        assert any(r["kind"] == "cut" and (float(r["start"]) > 1000.0
                                           or float(r["end"]) < 2549.07)
                   for r in rows), rows
    else:
        # the listed wall still stands on fill: its lead-in at 21+99 lies in
        # the band before it
        f = ifcopenshell.open(str(out / "road-corridor.ifc"))
        fills = {e.Name for e in f.by_type("IfcEarthworksFill")}
        assert {"Fill STA 21+00.00 to 22+00.00",
                "Fill STA 22+00.00 to 23+00.00"} <= fills
