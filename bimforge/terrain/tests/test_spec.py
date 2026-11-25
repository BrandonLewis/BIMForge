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

