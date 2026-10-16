"""terrain/attach: the fetch -> shift -> mesh -> carve -> provenance orchestration.

Offline and deterministic: the collaborators (fetch_3dep_dem / fetch_3dep_lpc,
ncat_vertshift, workunit_meta, carve) are monkeypatched AT THE ATTACH MODULE'S
NAMES; grid_to_mesh and build_provenance run for real so the test exercises the
actual wiring between them.
"""
import uuid

import numpy as np
import pytest

from bimforge.author.model import StructureModel
from bimforge.author.project import ProjectContext
from bimforge.terrain import attach as A
from bimforge.terrain.grid import TerrainGrid

FT = 1.0 / 0.3048


def _model():
    ctx = ProjectContext(name="Terrain Fixture", epsg=26942,
                         guid_ns=uuid.UUID(int=11))
    return StructureModel("terrain", ctx)


def _grid(crs_epsg=26942, info=None):
    z = np.full((4, 4), 10.0)
    return TerrainGrid(z=z, bbox_m=(0.0, 0.0, 4.0, 4.0), spacing_m=1.0,
                       crs_epsg=crs_epsg, info=dict(info or {}))


def _never(*a, **k):
    raise AssertionError("collaborator should not have been called")


# ------------------------------------------------------------ DEM, explicit shift

def test_attach_dem_explicit_vshift_no_cuts(tmp_path, monkeypatch):
    seen = {}

    def fake_dem(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False,
                 log=print):
        seen.update(bbox=bbox_m, spacing=spacing_m, crs=crs_epsg,
                    cache=str(cache_path), refresh=refresh)
        return _grid()

    monkeypatch.setattr(A, "fetch_3dep_dem", fake_dem)
    monkeypatch.setattr(A, "ncat_vertshift", _never)   # explicit vshift_m wins
    monkeypatch.setattr(A, "workunit_meta", _never)    # no lon/lat -> skipped
    monkeypatch.setattr(A, "carve", _never)            # cuts=() -> no carve
    m = _model()
    logs = []
    el = A.attach_terrain(m, (0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                          cache_stem=str(tmp_path / "site"), unit_scale=FT,
                          spacing_m=1.0, vshift_m=0.5, log=logs.append)
    assert len(m.elements) == 1 and el is m.elements[0]
    assert el.name.startswith("Existing ground")
    assert "USGS 3DEP DEM" in el.name
    assert "carved" not in el.name                     # no carve happened
    assert el.ifc_class == "IfcGeographicElement"
    assert el.predefined_type == "TERRAIN"
    assert el.classifications == []                    # reference geometry
    assert el.quantities == {}
    g = el.geometry
    assert g["kind"] == "mesh"
    assert g["units"] == "ft"
    assert len(g["verts"]) == 16                       # 4x4, all valid
    assert len(g["tris"]) == 18                        # 3x3 quads x 2
    # z = (z_m - vshift_m) * unit_scale, the single datum/unit conversion.
    assert g["verts"][0][2] == pytest.approx((10.0 - 0.5) * FT)
    prov = g["provenance"]
    assert prov["Source"] == "USGS 3DEP 1m DEM"
    assert prov["AppliedVerticalShift"] == pytest.approx(-0.5)
    assert prov["SourceCRS"] == "EPSG:26942 / EPSG:5703"
    assert prov["Carved"] is False
    assert prov["SurveyGrade"] is False
    assert "SourceWorkUnit" not in prov                # vintage skipped
    # the fetcher got the caller's bbox/CRS and a cache path off the stem
    assert seen["bbox"] == (0.0, 0.0, 4.0, 4.0)
    assert seen["crs"] == 26942
    assert seen["cache"].endswith("-3DEP-DEM.tif")
    assert any("vintage skipped" in ln for ln in logs)


def test_attach_requires_a_vertical_shift(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", lambda *a, **k: _grid())
    with pytest.raises(ValueError, match="vshift"):
        A.attach_terrain(_model(), (0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                         cache_stem=str(tmp_path / "s"), unit_scale=FT)


# --------------------------------------------------- NCAT lookup + workunit

def test_attach_vshift_lookup_drives_ncat_and_workunit(tmp_path, monkeypatch):
    calls = {}

    def fake_shift(lat, lon, cache_path, *, fallback=None, log=print, **kw):
        calls["ncat"] = (lat, lon, str(cache_path), fallback)
        return 0.5

    def fake_wu(lon, lat, cache_path, log=print):
        calls["wu"] = (lon, lat, str(cache_path))
        return {"project": "CA_Test_2020", "workunit": "CA_Test_2020_A",
                "collect_start": "2020-02-01", "collect_end": "2020-03-01",
                "ql": "QL2"}

    fb = lambda lat, lon: 0.643
    monkeypatch.setattr(A, "fetch_3dep_dem", lambda *a, **k: _grid())
    monkeypatch.setattr(A, "ncat_vertshift", fake_shift)
    monkeypatch.setattr(A, "workunit_meta", fake_wu)
    m = _model()
    el = A.attach_terrain(m, (0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                          cache_stem=str(tmp_path / "site"), unit_scale=FT,
                          vshift_lookup=(38.0, -120.0, fb), log=lambda s: None)
    lat, lon, cache, fallback = calls["ncat"]
    assert (lat, lon) == (38.0, -120.0)
    assert cache.endswith("-3DEP-vshift.json")
    assert fallback is fb
    # workunit lon/lat derive from the lookup tuple (lat, lon) -> (lon, lat)
    wlon, wlat, wcache = calls["wu"]
    assert (wlon, wlat) == (-120.0, 38.0)
    assert wcache.endswith("-3DEP-workunit.json")
    prov = el.geometry["provenance"]
    assert prov["AppliedVerticalShift"] == pytest.approx(-0.5)
    assert prov["SourceWorkUnit"] == "CA_Test_2020_A"
    assert prov["QualityLevel"] == "QL2"


# ------------------------------------------------------------------- carve

def test_attach_with_cuts_carves_and_stamps_provenance(tmp_path, monkeypatch):
    cut = ([(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)],
           [(-2.0, -2.0), (-2.0, 12.0), (12.0, 12.0), (12.0, -2.0)],
           -5.0, 30.0)
    seen = {}

    def fake_carve(verts, tris, cuts, log=print):
        seen["cuts"] = cuts
        return verts, tris, True, 100.0

    monkeypatch.setattr(A, "fetch_3dep_dem", lambda *a, **k: _grid())
    monkeypatch.setattr(A, "carve", fake_carve)
    m = _model()
    el = A.attach_terrain(m, (0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                          cache_stem=str(tmp_path / "site"), unit_scale=FT,
                          vshift_m=0.5, cuts=(cut,), log=lambda s: None)
    assert list(seen["cuts"]) == [cut]
    assert el.geometry["provenance"]["Carved"] is True
    assert el.name.endswith("(excavation carved)")


# --------------------------------------------------------------------- LPC

def test_attach_lpc_builds_wgs_bbox_and_names_lidar(tmp_path, monkeypatch):
    pytest.importorskip("pyproj")
    seen = {}

    def fake_lpc(bbox_m, spacing_m, crs_epsg, wgs_bbox, cache_stem,
                 refresh=False, log=print):
        seen.update(bbox=bbox_m, crs=crs_epsg, wgs=wgs_bbox,
                    stem=str(cache_stem))
        return _grid(crs_epsg=crs_epsg,
                     info={"project": "CA_P", "tiles": 1,
                           "publication": "2020-01-01"})

    monkeypatch.setattr(A, "fetch_3dep_lpc", fake_lpc)
    monkeypatch.setattr(A, "fetch_3dep_dem", _never)
    m = _model()
    # crs_epsg=4326 makes the pyproj transform an identity, so the WGS
    # discovery bbox is checkable exactly.
    el = A.attach_terrain(m, (-120.0, 38.0, -119.99, 38.01), crs_epsg=4326,
                          cache_stem=str(tmp_path / "site"), unit_scale=FT,
                          source="lpc", vshift_m=0.5, log=lambda s: None)
    lo1, la1, lo2, la2 = [float(x) for x in seen["wgs"].split(",")]
    assert (lo1, la1) == pytest.approx((-120.0, 38.0))
    assert (lo2, la2) == pytest.approx((-119.99, 38.01))
    assert seen["crs"] == 4326
    assert "lidar" in el.name
    prov = el.geometry["provenance"]
    assert prov["Source"].startswith("USGS 3DEP Lidar")
    assert prov["SourceProject"] == "CA_P"
    # the grid's crs_epsg reaches provenance through the info dict
    assert prov["SourceCRS"] == "EPSG:4326 / EPSG:5703"
