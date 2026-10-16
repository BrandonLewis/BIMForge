"""Offline tests for terrain/datum.py — NCAT vertical-datum shift.

All transport goes through the module-level ``_urlopen(url, timeout)`` seam,
monkeypatched here; no test touches the network.
"""

import json

import pytest

from bimforge.terrain import datum


def _no_transport(url, timeout):
    raise AssertionError("transport touched when it should not have been")


def test_cache_hit_returns_shift_without_transport(tmp_path, monkeypatch):
    cache = tmp_path / "vertshift.json"
    cache.write_text(json.dumps({
        "shift_m": 0.701, "source": "NOAA NCAT VERTCON 3.0",
        "lat": 45.0, "lon": -122.0,
    }))
    monkeypatch.setattr(datum, "_urlopen", _no_transport)
    shift = datum.ncat_vertshift(45.0, -122.0, cache, log=lambda m: None)
    assert shift == pytest.approx(0.701)


def test_authority_path_parses_ncat_json_and_caches(tmp_path, monkeypatch):
    calls = []
    payload = json.dumps({"srcOrthoht": "0.000", "destOrthoht": "0.712"}).encode()

    def fake_urlopen(url, timeout):
        calls.append(url)
        return payload

    monkeypatch.setattr(datum, "_urlopen", fake_urlopen)
    cache = tmp_path / "vertshift.json"
    shift = datum.ncat_vertshift(45.5, -122.5, cache, log=lambda m: None)

    assert shift == pytest.approx(0.712)
    assert len(calls) == 1
    url = calls[0]
    assert "inVertDatum=NGVD29" in url
    assert "outVertDatum=NAVD88" in url
    cached = json.loads(cache.read_text())
    assert cached["shift_m"] == pytest.approx(0.712)
    assert cached["source"] == "NOAA NCAT VERTCON 3.0"
    assert cached["lat"] == 45.5
    assert cached["lon"] == -122.5


def test_vert_datum_parameters_reach_the_query(tmp_path, monkeypatch):
    calls = []
    payload = json.dumps({"srcOrthoht": 0.0, "destOrthoht": -0.05}).encode()
    monkeypatch.setattr(
        datum, "_urlopen",
        lambda url, timeout: calls.append(url) or payload)
    shift = datum.ncat_vertshift(
        44.0, -121.0, tmp_path / "s.json",
        in_vert="NAVD88", out_vert="NGVD29", log=lambda m: None)
    assert shift == pytest.approx(-0.05)
    assert "inVertDatum=NAVD88" in calls[0]
    assert "outVertDatum=NGVD29" in calls[0]


def test_unreachable_uses_fallback_with_logged_warning(tmp_path, monkeypatch):
    def down(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(datum, "_urlopen", down)
    logs = []
    cache = tmp_path / "vertshift.json"
    shift = datum.ncat_vertshift(
        45.0, -122.0, cache,
        fallback=lambda lat, lon: 0.643, log=logs.append)

    assert shift == pytest.approx(0.643)
    cached = json.loads(cache.read_text())
    assert cached["shift_m"] == pytest.approx(0.643)
    # Source string names the fallback, not the authority.
    assert "fallback" in cached["source"]
    assert "NCAT unreachable" in cached["source"]
    assert any("NCAT unreachable" in m for m in logs)


def test_unreachable_without_fallback_raises_naming_ncat(tmp_path, monkeypatch):
    def down(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(datum, "_urlopen", down)
    cache = tmp_path / "vertshift.json"
    with pytest.raises(RuntimeError, match="NCAT"):
        datum.ncat_vertshift(45.0, -122.0, cache, log=lambda m: None)
    assert not cache.exists()


# ---------------------------------------------------------------------------
# geoid_shift_m — NAVD88 -> EGM96 pin-plus-reverify with liveness assertion.
# pyproj goes through the module-level ``_egm96_transformer()`` seam,
# monkeypatched here; no test needs pyproj or the PROJ geoid grids.
# ---------------------------------------------------------------------------

class _FakeTransformer:
    """transform(lon, lat, z) -> (lon, lat, z + shift).

    shift=0.0 reproduces pyproj's silent null transform: the height comes
    back untouched, with no warning at all.
    """

    def __init__(self, shift):
        self.shift = shift

    def transform(self, lon, lat, z):
        return lon, lat, z + self.shift


def _no_pyproj():
    raise RuntimeError('pyproj is required — pip install "bimforge[terrain]"')


def test_geoid_pin_stands_alone_when_grids_unreachable(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer", lambda: None)
    logs = []
    shift = datum.geoid_shift_m(38.0, -121.0, pin=-0.118, log=logs.append)
    assert shift == pytest.approx(-0.118)
    assert not any("WARNING" in m for m in logs)


def test_geoid_pin_stands_alone_without_pyproj(monkeypatch):
    # The bimforge[terrain] RuntimeError belongs to the no-pin path only; a
    # pinned shift must keep working on a machine without pyproj at all.
    monkeypatch.setattr(datum, "_egm96_transformer", _no_pyproj)
    shift = datum.geoid_shift_m(38.0, -121.0, pin=-0.118, log=lambda m: None)
    assert shift == pytest.approx(-0.118)


def test_geoid_pin_reverify_agreement_is_quiet(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(-0.120))
    logs = []
    shift = datum.geoid_shift_m(38.0, -121.0, pin=-0.118, log=logs.append)
    assert shift == pytest.approx(-0.118)
    assert not any("WARNING" in m for m in logs)


def test_geoid_pin_reverify_warns_on_disagreement(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(-0.90))
    logs = []
    shift = datum.geoid_shift_m(38.0, -121.0, pin=-0.118, log=logs.append)
    # The pin still wins — the warning asks for a human, it never fails.
    assert shift == pytest.approx(-0.118)
    warned = [m for m in logs if "WARNING" in m]
    assert len(warned) == 1
    assert "-0.90000" in warned[0] and "-0.11800" in warned[0]


def test_geoid_pin_null_rederivation_never_warns(monkeypatch):
    # A dead transform (grids present but not running) re-derives a shift of
    # exactly 0; that is "unreachable", not a disagreement with the pin.
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(0.0))
    logs = []
    shift = datum.geoid_shift_m(38.0, -121.0, pin=-0.118, log=logs.append)
    assert shift == pytest.approx(-0.118)
    assert not any("WARNING" in m for m in logs)


def test_geoid_no_pin_derives_live_shift(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(-0.712))
    shift = datum.geoid_shift_m(38.0, -121.0, log=lambda m: None)
    assert shift == pytest.approx(-0.712)


def test_geoid_no_pin_null_transform_raises(monkeypatch):
    # LIVENESS: pyproj null-transforms silently when the geoid grids are
    # missing — a zero shift where a real separation is expected must RAISE.
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(0.0))
    with pytest.raises(RuntimeError, match="null-transform"):
        datum.geoid_shift_m(38.0, -121.0, log=lambda m: None)


def test_geoid_no_pin_implausible_shift_raises(monkeypatch):
    # A shift far beyond any CONUS geoid separation is a unit/CRS blunder
    # (e.g. feet fed through as metres), not a geoid difference.
    monkeypatch.setattr(datum, "_egm96_transformer",
                        lambda: _FakeTransformer(50.0))
    with pytest.raises(RuntimeError, match="looks dead"):
        datum.geoid_shift_m(38.0, -121.0, log=lambda m: None)


def test_geoid_no_pin_unreachable_grids_raise_asking_for_pin(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer", lambda: None)
    with pytest.raises(RuntimeError, match="pin"):
        datum.geoid_shift_m(38.0, -121.0, log=lambda m: None)


def test_geoid_no_pin_without_pyproj_raises_naming_extra(monkeypatch):
    monkeypatch.setattr(datum, "_egm96_transformer", _no_pyproj)
    with pytest.raises(RuntimeError, match=r"bimforge\[terrain\]"):
        datum.geoid_shift_m(38.0, -121.0, log=lambda m: None)


# --------------------------------------------------------------------------
# Grid availability (issue #134). PROJ can offer a DEGRADED operation when the
# geoid grid it actually wants is missing: pyproj warns "Best transformation
# is not available due to missing Grid(short_name=us_nga_egm96_15.tif ...)"
# and still hands back a transformer. At lat 38.02 / lon -120.33 that returned
# 0.0196 m — a null-transform artefact that CLEARS the 0.01 m liveness floor
# and so was returned as if it had been derived. A real NAVD88->EGM96
# separation in the California foothills is decimetres.
# --------------------------------------------------------------------------

class _FakeGroup:
    def __init__(self, transformers, best_available, unavailable=()):
        self.transformers = list(transformers)
        self.best_available = best_available
        self.unavailable_operations = list(unavailable)


def test_degraded_operation_without_the_best_grid_counts_as_unreachable(
        monkeypatch):
    """A transformer EXISTS but PROJ says it is not the best available: the
    grids are missing, so this must read as 'unreachable', never as a
    derivation."""
    monkeypatch.setattr(
        datum, "_transformer_group",
        lambda a, b: _FakeGroup([object()], best_available=False,
                                unavailable=["us_nga_egm96_15.tif"]))
    assert datum._egm96_transformer() is None


def test_no_pin_with_a_degraded_operation_raises_instead_of_returning_it(
        monkeypatch):
    """The reported bug end to end: without a pin, a degraded operation must
    RAISE asking for a pin rather than silently returning 0.0196 m."""
    monkeypatch.setattr(
        datum, "_transformer_group",
        lambda a, b: _FakeGroup([_FakeTransformer(0.0196)],
                                best_available=False,
                                unavailable=["us_nga_egm96_15.tif"]))
    with pytest.raises(RuntimeError, match="pin"):
        datum.geoid_shift_m(38.0196, -120.3255, log=lambda m: None)


def test_best_available_operation_is_used(monkeypatch):
    """The other side: when PROJ has the real grids, the shift is derived."""
    monkeypatch.setattr(
        datum, "_transformer_group",
        lambda a, b: _FakeGroup([_FakeTransformer(-0.85)],
                                best_available=True))
    assert datum.geoid_shift_m(38.0, -121.0,
                               log=lambda m: None) == pytest.approx(-0.85)
