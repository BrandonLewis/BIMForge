"""terrain/spec: the `terrain:` block and the vertical datum rule (G.9).

Offline: NCAT's transport (bimforge.terrain.datum._urlopen) is replaced."""
import json
import uuid

import pytest

from bimforge.author.project import ProjectContext
from bimforge.terrain import datum as D
from bimforge.terrain import spec as S


def ctx(vd=None, epsg=2226):
    return ProjectContext(name="t", epsg=epsg, base_e=6594000.0,
                          base_n=1943000.0, vertical_datum=vd,
                          guid_ns=uuid.UUID(int=3))


def test_parse_defaults_and_resolves_the_cache_against_the_spec(tmp_path):
    ts = S.parse({"cache": "terrain/site"}, tmp_path)
    assert ts == S.TerrainSpec(cache=str(tmp_path / "terrain" / "site"))
    assert (ts.source, ts.margin_ft, ts.spacing_m, ts.vshift_m, ts.refresh) == (
        "dem", 200.0, 1.0, None, False)
    lp = S.parse({"cache": str(tmp_path / "x"), "source": "LPC",
                  "margin_ft": 50, "spacing_m": 2, "vshift_m": 0.7}, None)
    assert (lp.cache, lp.source, lp.margin_ft, lp.spacing_m, lp.vshift_m) == (
        str(tmp_path / "x"), "lpc", 50.0, 2.0, 0.7)


@pytest.mark.parametrize("block, match", [
    ({}, "needs `cache`"),
    ({"cache": "x", "source": "srtm"}, "not dem or lpc"),
    ({"cache": "x", "bbox": [0, 0, 1, 1]}, r"unknown keys \['bbox'\]"),
    ("dem", "must be a mapping"),
])
def test_parse_refuses(block, match):
    with pytest.raises(ValueError, match=match):
        S.parse(block, None)


def test_from_ground_reads_the_0_1_132_form():
    ts = S.from_ground({"source": "3dep", "cache": "c", "spacing_m": 2.0,
                        "margin_ft": 40.0, "vshift_m": 0.5})
    assert ts == S.TerrainSpec(cache="c", spacing_m=2.0, margin_ft=40.0,
                               vshift_m=0.5)


@pytest.mark.parametrize("vd", ["NAVD88", "navd 88", "NAVD-88"])
def test_navd88_needs_no_shift(vd, tmp_path):
    assert S.terrain_vshift(ctx(vd), tmp_path / "s") == (0.0, "NAVD88: none")


def test_an_explicit_shift_wins(tmp_path):
    assert S.terrain_vshift(ctx("NGVD29"), tmp_path / "s", 0.7) == (
        0.7, "spec vshift_m")


def test_ngvd29_asks_ncat_once_then_reads_the_cache(tmp_path, monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        return json.dumps({"srcOrthoht": 0.0, "destOrthoht": 0.713})

    monkeypatch.setattr(D, "_urlopen", fake)
    stem = tmp_path / "sub" / "s"
    got = S.terrain_vshift(ctx("NGVD 29"), stem, log=lambda *_: None)
    assert got == (pytest.approx(0.713), "NOAA NCAT VERTCON 3.0")
    assert len(calls) == 1 and "lat=38." in calls[0]   # the base point's latitude
    again = S.terrain_vshift(ctx("NGVD29"), stem, log=lambda *_: None)
    assert again == got and len(calls) == 1


def test_ngvd29_without_ncat_fails(tmp_path, monkeypatch):
    def down(url, timeout):
        raise OSError("no route")

    monkeypatch.setattr(D, "_urlopen", down)
    with pytest.raises(ValueError, match="give terrain.vshift_m"):
        S.terrain_vshift(ctx("NGVD29"), tmp_path / "s", log=lambda *_: None)


@pytest.mark.parametrize("vd", [None, "MLLW"])
def test_another_datum_fails(vd, tmp_path):
    with pytest.raises(ValueError, match="has no rule; give terrain.vshift_m"):
        S.terrain_vshift(ctx(vd), tmp_path / "s")


def test_crs_per_ft_and_the_base_lonlat():
    assert S.crs_per_ft(ctx()) == pytest.approx(1.0)          # ftUS under ftUS
    lon, lat = S.base_lonlat(ctx())
    assert -123.0 < lon < -120.0 and 37.0 < lat < 40.0      # CA zone 2


import numpy as np

from bimforge.author.model import Element, StructureModel
from bimforge.terrain import attach as A
from bimforge.terrain.grid import TerrainGrid


def _box(name, x, y, bearing=0.0):
    return Element(name, ifc_class="IfcWall", x_ft=x, y_ft=y, bearing_deg=bearing,
                   geometry={"kind": "prism", "base": [(0, 0), (10, 0), (10, 2), (0, 2)],
                             "z_bot": 0.0, "z_top": 5.0})


def test_the_footprint_is_the_placed_plan_extent_in_survey_feet():
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    m.add(_box("a", 0.0, 0.0))
    m.add(_box("b", 100.0, 50.0, bearing=90.0))   # base turned to run north
    A.add_terrain(m, "old ground", [(0.0, -9999.0, 0.0)], [], {})  # left out
    e0, n0, e1, n1 = S.model_footprint(m, c)
    assert (e0, n0) == pytest.approx((6594000.0, 1943000.0))
    # b's (10, 2) corner turned 90 deg: (-2, 10), placed at (98, 60)
    assert (e1, n1) == pytest.approx((6594000.0 + 100.0, 1943000.0 + 60.0))


def test_a_model_with_no_geometry_has_no_footprint():
    with pytest.raises(ValueError, match="no geometry"):
        S.model_footprint(StructureModel("e", ctx("NAVD88")), ctx("NAVD88"))


def _flat(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
    xmin, ymin, xmax, ymax = bbox_m
    cols = max(2, round((xmax - xmin) / spacing_m))
    rows = max(2, round((ymax - ymin) / spacing_m))
    return TerrainGrid(z=np.full((rows, cols), 30.48), bbox_m=bbox_m,
                       spacing_m=spacing_m, crs_epsg=crs_epsg)


def test_attach_over_adds_one_ground_in_the_model_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    ts = S.TerrainSpec(cache=str(tmp_path / "t" / "site"), margin_ft=20.0,
                       spacing_m=2.0)
    el, _grid, shift = S.attach_over(m, c, ts, (6594000.0, 1943000.0,
                                               6594100.0, 1943060.0),
                                    log=lambda *_: None)
    assert m.elements == [el] and A.is_terrain(el) and shift == 0.0
    xs = [v[0] for v in el.geometry["verts"]]
    ys = [v[1] for v in el.geometry["verts"]]
    zs = {round(v[2], 6) for v in el.geometry["verts"]}
    # pixel centres inside the footprint grown by 20 ft, model frame
    assert -20.0 < min(xs) < 0.0 and 100.0 < max(xs) < 120.0
    assert -20.0 < min(ys) < 0.0 and 60.0 < max(ys) < 80.0
    assert zs == {round(30.48 / c.ft_to_m - c.base_h, 6)}
    prov = el.geometry["provenance"]
    assert prov["VerticalShiftSource"] == "NAVD88: none"
    assert prov["MeshSpacing"] == pytest.approx(2.0 / c.ft_to_m)   # 2 m in ftUS


def test_add_spec_terrain_adds_none_when_the_model_has_ground(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    m.add(_box("a", 0.0, 0.0))
    ts = S.TerrainSpec(cache=str(tmp_path / "site"), spacing_m=10.0)
    S.add_spec_terrain(m, c, ts, log=lambda *_: None)
    S.add_spec_terrain(m, c, ts, log=lambda *_: None)
    assert sum(A.is_terrain(e) for e in m.elements) == 1


def test_the_report_names_the_footprint_source_and_shift(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {
        "project": "CA_NoCAL_2018", "workunit": "W1", "collect_start": "2018-04-01",
        "collect_end": "2018-05-01", "ql": "QL2"})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    ts = S.TerrainSpec(cache=str(tmp_path / "site"), spacing_m=10.0)
    (tmp_path / "site-3DEP-DEM.tif").write_bytes(b"x")   # a cache file to list
    el, _g, _s = S.attach_over(m, c, ts, (6594000.0, 1943000.0, 6594100.0,
                                          1943060.0), log=lambda *_: None)
    text = "\n".join(S.report_lines(el, c, ts))
    for want in ("Existing ground - USGS 3DEP DEM", "footprint: E 6,59", "ft",
                 "CA_NoCAL_2018", "2018-04-01 to 2018-05-01", "QL2",
                 "shift 0.000 m (NAVD88: none)", "site-3DEP-DEM.tif"):
        assert want in text, want
