"""terrain/fetch: DEM fetch (cache / URL / retry), mean binning, workunit meta.

Offline and deterministic: every transport call goes through the module-level
_urlopen/_urlretrieve seam, monkeypatched here. The DEM fixture is a tiny
float32 TIFF built in-memory with Pillow.
"""
import io
import json
import time
import urllib.parse

import numpy as np
import pytest

from bimforge.terrain import fetch as F


def _tiff_bytes(arr):
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.fromarray(np.asarray(arr, dtype="float32"), mode="F").save(
        buf, format="TIFF")
    return buf.getvalue()


def _no_transport(url, timeout):
    raise AssertionError(f"transport touched: {url}")


# ---------------------------------------------------------------- DEM fetch

def test_dem_cache_hit_skips_transport(tmp_path, monkeypatch):
    raw = _tiff_bytes([[1.0, 2.0], [3.0, 4.0]])
    cache = tmp_path / "dem.tif"
    cache.write_bytes(raw)
    monkeypatch.setattr(F, "_urlopen", _no_transport)
    logs = []
    g = F.fetch_3dep_dem((0.0, 0.0, 2.0, 2.0), 1.0, 32610, cache,
                         refresh=False, log=logs.append)
    assert g.z.shape == (2, 2)
    assert g.z.dtype == np.float64
    assert g.z[0, 0] == pytest.approx(1.0)
    assert g.bbox_m == (0.0, 0.0, 2.0, 2.0)
    assert g.spacing_m == 1.0
    assert g.crs_epsg == 32610
    assert any("cache hit" in ln for ln in logs)


def test_dem_fetch_url_params_and_cache_write(tmp_path, monkeypatch):
    raw = _tiff_bytes([[1.0, 2.0], [3.0, 4.0]])
    seen = {}

    def fake(url, timeout):
        seen["url"] = url
        return io.BytesIO(raw)

    monkeypatch.setattr(F, "_urlopen", fake)
    cache = tmp_path / "dem.tif"
    g = F.fetch_3dep_dem((0.0, 0.0, 2.0, 2.0), 1.0, 32610, cache,
                         refresh=False, log=lambda s: None)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert q["bboxSR"] == ["32610"]
    assert q["imageSR"] == ["32610"]
    assert q["size"] == ["2,2"]
    assert q["pixelType"] == ["F32"]
    assert q["adjustAspectRatio"] == ["false"]
    assert cache.read_bytes() == raw          # raw TIFF cached for offline rebuilds
    assert g.z.shape == (2, 2)


def test_dem_retry_then_success(tmp_path, monkeypatch):
    raw = _tiff_bytes([[5.0, 6.0], [7.0, 8.0]])
    calls = {"n": 0}

    def flaky(url, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("502 Bad Gateway")
        return io.BytesIO(raw)

    monkeypatch.setattr(F, "_urlopen", flaky)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    logs = []
    g = F.fetch_3dep_dem((0.0, 0.0, 2.0, 2.0), 1.0, 32610, tmp_path / "dem.tif",
                         refresh=True, log=logs.append)
    assert calls["n"] == 3
    attempts = [ln for ln in logs if "attempt" in ln]
    assert len(attempts) == 2
    assert g.z.shape == (2, 2)


# ------------------------------------------------------------- mean binning

def test_bin_points_mean_not_lowest():
    # 2x2 bbox at 1 m spacing. Cell (0, 0) gets returns [1.0, 3.0]: the bin is
    # their MEAN 2.0, NOT the lowest 1.0 — the mean-vs-lowest regression test.
    E = np.array([0.5, 0.6, 1.5, 0.5, 5.0])
    N = np.array([1.5, 1.4, 1.5, 0.5, 1.5])
    Z = np.array([1.0, 3.0, 7.0, 9.0, 99.0])
    z = F.bin_points(E, N, Z, (0.0, 0.0, 2.0, 2.0), 1.0)
    assert z.shape == (2, 2)
    assert z[0, 0] == pytest.approx(2.0)
    assert z[0, 1] == pytest.approx(7.0)
    assert z[1, 0] == pytest.approx(9.0)
    assert np.isnan(z[1, 1])                  # empty cell; out-of-bbox 99 dropped


def test_bin_points_drops_out_of_bbox():
    E = np.array([-1.0, 0.5, 3.0])
    N = np.array([0.5, -2.0, 1.5])
    Z = np.array([100.0, 200.0, 300.0])
    z = F.bin_points(E, N, Z, (0.0, 0.0, 2.0, 2.0), 1.0)
    assert np.isnan(z).all()


# ------------------------------------------------------------ workunit meta

_WU_PAYLOAD = {"features": [{"attributes": {
    "project": "CA_TestProject_2020",
    "workunit": "CA_TestProject_2020_A",
    "collect_start": 1580515200000,           # 2020-02-01 UTC, epoch ms
    "collect_end": 1583020800000,             # 2020-03-01 UTC, epoch ms
    "ql": "QL2"}}]}


def test_workunit_meta_parses_and_caches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake(url, timeout):
        calls["n"] += 1
        return io.BytesIO(json.dumps(_WU_PAYLOAD).encode())

    monkeypatch.setattr(F, "_urlopen", fake)
    cache = tmp_path / "workunit.json"
    logs = []
    meta = F.workunit_meta(-120.0, 38.0, cache, log=logs.append)
    assert meta == {"project": "CA_TestProject_2020",
                    "workunit": "CA_TestProject_2020_A",
                    "collect_start": "2020-02-01",
                    "collect_end": "2020-03-01",
                    "ql": "QL2"}
    # Cache round-trip: the second call reads the JSON, no transport.
    monkeypatch.setattr(F, "_urlopen", _no_transport)
    again = F.workunit_meta(-120.0, 38.0, cache, log=logs.append)
    assert again == meta
    assert calls["n"] == 1


def test_workunit_meta_unreachable_returns_empty(tmp_path, monkeypatch):
    def boom(url, timeout):
        raise OSError("index down")

    monkeypatch.setattr(F, "_urlopen", boom)
    logs = []
    meta = F.workunit_meta(-120.0, 38.0, tmp_path / "workunit.json",
                           log=logs.append)
    assert meta == {}                          # the build continues without vintage
    assert any("skipped" in ln for ln in logs)
