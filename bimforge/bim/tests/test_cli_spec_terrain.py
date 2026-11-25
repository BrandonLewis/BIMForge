"""est-bim terrain (G.9): fetch a spec's ground ahead of the build. (The
contour and terrain-diff commands are tested in test_cli_terrain.py.)"""
from bimforge.author.tests.test_spec_terrain import b3_spec, offline
from bimforge.bim import cli


def test_it_fetches_once_then_reads_the_cache(tmp_path, monkeypatch, capsys):
    calls = []
    offline(monkeypatch, calls)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0})
    assert cli.main(["terrain", str(p)]) == 0
    out = capsys.readouterr().out
    assert "Existing ground - USGS 3DEP DEM" in out
    assert "shift 0.000 m (NAVD88: none)" in out and "QL2" in out
    assert any("exportImage" in u for u in calls)
    fetched = len(calls)
    assert cli.main(["terrain", str(p)]) == 0           # all from the cache
    assert len(calls) == fetched
    assert cli.main(["terrain", str(p), "--refresh"]) == 0
    assert sum("exportImage" in u for u in calls) == 2


def test_a_spec_without_terrain_says_so(tmp_path, capsys):
    p = b3_spec(tmp_path)
    assert cli.main(["terrain", str(p)]) == 0
    assert "terrain: the spec asks for no terrain" in capsys.readouterr().out


def test_a_cache_of_another_area_fails_the_build_until_refreshed(
        tmp_path, monkeypatch, capsys):
    from bimforge.author.families import registry as R
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0})
    assert cli.main(["terrain", str(p)]) == 0
    longer = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0,
                                "margin_ft": 400.0})
    capsys.readouterr()
    assert cli.main(["build", str(longer)]) == 1
    err = capsys.readouterr().err
    assert "site-3DEP-DEM.tif" in err and "est-bim terrain SPEC --refresh" in err
    assert cli.main(["terrain", str(longer), "--refresh"]) == 0
    assert R.build_from_spec(longer) == 0
