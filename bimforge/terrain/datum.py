"""Vertical-datum authority — NOAA NCAT (VERTCON 3.0) shift lookup, plus the
NAVD88 -> EGM96 geoid shift for KML absolute altitudes.

Authority-first, fallback-named, nothing silent: the NCAT shift comes from
NOAA unless it is unreachable, in which case a caller-supplied fallback is
used with a logged warning and a source string that names the fallback; the
geoid shift is pin-plus-reverify with a liveness assertion, because pyproj
will happily null-transform a height with no warning at all.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

NCAT_URL = "https://geodesy.noaa.gov/api/ncat/llh"


def _urlopen(url, timeout):
    """Transport seam (module-level so tests monkeypatch ONE name).

    Returns the response body as bytes.
    """
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def ncat_vertshift(lat, lon, cache_path, *, in_vert="NGVD29",
                   out_vert="NAVD88", fallback=None, log=print):
    """``in_vert`` -> ``out_vert`` shift in metres at (lat, lon) from NOAA NCAT
    (VERTCON 3.0), cached to a small JSON.

    NCAT 3.0 is the authority for tying a NAVD88 product (3DEP) to a surveyed
    NGVD29 model; it can differ ~0.1 m from an older local VERTCON grid, so do
    not substitute a project datum's grid unless NCAT is unreachable - and
    warn when falling back.

    ``fallback(lat, lon) -> shift_m`` is consulted only when NCAT is
    unreachable; the cached/logged source string then names the fallback. With
    no fallback, an unreachable NCAT raises ``RuntimeError``.

    The cache records ``{shift_m, source, lat, lon}`` so the provenance of a
    cached shift (authority vs fallback) survives across runs.
    """
    cache_path = Path(cache_path)
    if cache_path.exists():
        return json.loads(cache_path.read_text())["shift_m"]
    try:
        q = {"lat": lat, "lon": lon, "orthoHt": 0.0,
             "inDatum": "NAD83(2011)", "outDatum": "NAD83(2011)",
             "inVertDatum": in_vert, "outVertDatum": out_vert}
        url = f"{NCAT_URL}?{urllib.parse.urlencode(q)}"
        d = json.loads(_urlopen(url, 30))
        shift = float(d["destOrthoht"]) - float(d["srcOrthoht"])
        src = "NOAA NCAT VERTCON 3.0"
    except Exception as e:
        if fallback is None:
            raise RuntimeError(
                f"NOAA NCAT unreachable ({e}) and no fallback supplied for "
                f"the {in_vert}->{out_vert} shift at ({lat}, {lon})") from e
        shift = float(fallback(lat, lon))
        name = getattr(fallback, "__name__", None) or "fallback"
        src = f"fallback {name} (NCAT unreachable)"
        log(f"  terrain: NCAT unreachable ({e}); fell back to {src}")
    cache_path.write_text(json.dumps({"shift_m": shift, "source": src,
                                      "lat": lat, "lon": lon}))
    log(f"  terrain: {in_vert}->{out_vert} shift {shift:.3f} m ({src})")
    return shift


# ---------------------------------------------------------------------------
# NAVD88 -> EGM96 geoid shift — pin-plus-reverify with a liveness assertion
# ---------------------------------------------------------------------------

_NAVD88_CRS = "EPSG:4326+EPSG:5703"  # WGS84 horizontal + NAVD88 height (m)
_EGM96_CRS = "EPSG:4326+EPSG:5773"   # WGS84 horizontal + EGM96 height (m)
_PROBE_M = 100.0                     # probe height; the shift is a pure offset
# A real NAVD88->EGM96 separation over CONUS is decimetres to ~1.5 m. A shift
# of exactly 0 is the signature of a silent null transform (the grids did not
# run); one beyond 3 m is a unit or CRS blunder, not a geoid difference.
_LIVE_MIN_M, _LIVE_MAX_M = 0.01, 3.0
_REVERIFY_TOL_M = 0.05


def _transformer_group(from_crs, to_crs):
    """pyproj TransformerGroup seam (module-level so tests monkeypatch ONE
    name). Raises RuntimeError naming the ``bimforge[terrain]`` extra when
    pyproj itself is missing."""
    try:
        from pyproj.transformer import TransformerGroup
    except ImportError as e:
        raise RuntimeError(
            "pyproj is required to derive the NAVD88->EGM96 geoid shift — "
            'pip install "bimforge[terrain]" (or pass a pinned shift)') from e
    return TransformerGroup(from_crs, to_crs, always_xy=True)


#: Grid PROJ was missing when `_egm96_transformer` last rejected a degraded
#: operation, so the raised error can name it. Best-effort provenance for the
#: message; nothing depends on it.
_missing_grid = ""


def _egm96_transformer():
    """pyproj seam (module-level so tests monkeypatch ONE name).

    Returns a NAVD88(m) -> EGM96(m) transformer, or None when PROJ has no
    USABLE operation for the pair.

    "Usable" means ``best_available`` — NOT merely "a transformer exists".
    PROJ will offer a DEGRADED operation when the geoid grid it actually
    wants is absent, warning "Best transformation is not available due to
    missing Grid(short_name=us_nga_egm96_15.tif ...)" and then
    null-transforming the height anyway. At lat 38.02 that produced
    0.0196 m, which CLEARS the 0.01 m liveness floor below and so was
    returned as though it had been derived (issue #134). A fallback that
    passes the liveness check is precisely what the liveness check exists to
    stop, so availability is settled HERE, before any probe runs.
    """
    global _missing_grid
    _missing_grid = ""
    group = _transformer_group(_NAVD88_CRS, _EGM96_CRS)
    if not group.transformers or not getattr(group, "best_available", True):
        unavailable = list(getattr(group, "unavailable_operations", []))
        if unavailable:
            _missing_grid = str(getattr(unavailable[0], "grids", unavailable[0]))
        return None
    return group.transformers[0]


def _probe_shift_m(transformer, lat, lon):
    _lon, _lat, z = transformer.transform(lon, lat, _PROBE_M)
    return z - _PROBE_M


def geoid_shift_m(lat, lon, *, pin=None, log=print):
    """NAVD88 -> EGM96 geoid separation in metres at (lat, lon).

    KML ``altitudeMode=absolute`` is height above the EGM96 geoid, while a
    US plan-set model is NAVD88 — two different geoid models, so a plain
    unit conversion is wrong by their local separation (typically a few
    decimetres). Add the returned shift to a NAVD88 metric height to get an
    EGM96 absolute altitude.

    Why pin-plus-reverify: the PROJ geoid grids are not bundled with pyproj
    and stream from cdn.proj.org, so with no network pyproj silently falls
    back to a null vertical transform — the height comes back untouched,
    with no warning at all (a 0.118 m altitude error was observed exactly
    this way). Two rules follow:

    * With ``pin`` (a shift derived once online and committed), the pin is
      authoritative and is always returned — offline builds never fail.
      Whenever pyproj CAN transform, the value is re-derived and a
      disagreement beyond 0.05 m is logged as a WARNING asking for a human;
      a null re-derivation is treated as "grids unreachable", not as a
      disagreement.
    * Without ``pin``, the shift is derived live and the LIVENESS assertion
      raises unless it looks like a real geoid separation
      (0.01 m < |shift| < 3 m) — a zero shift means the grids did not run.
    """
    if pin is not None:
        pin = float(pin)
        try:
            transformer = _egm96_transformer()
            if transformer is not None:
                shift = _probe_shift_m(transformer, lat, lon)
                if (_LIVE_MIN_M < abs(shift) < _LIVE_MAX_M
                        and abs(shift - pin) > _REVERIFY_TOL_M):
                    log(f"WARNING: geoid separation from PROJ "
                        f"({shift:+.5f} m) disagrees with the pinned value "
                        f"({pin:+.5f} m) by {abs(shift - pin):.4f} m — check "
                        "the pin before trusting absolute altitudes")
        except Exception:
            pass  # no pyproj / no grids / dead transform: the pin stands alone
        return pin
    transformer = _egm96_transformer()  # RuntimeError names bimforge[terrain]
    if transformer is None:
        detail = f" (missing {_missing_grid})" if _missing_grid else ""
        raise RuntimeError(
            "PROJ has no usable NAVD88->EGM96 operation"
            f"{detail} — the geoid grids stream from cdn.proj.org and are "
            "not bundled with pyproj. A degraded operation is NOT used as a "
            "substitute: it null-transforms the height and returns a value "
            "small enough to look real. Derive the shift once online and "
            "pass it as pin=")
    shift = _probe_shift_m(transformer, lat, lon)
    if not _LIVE_MIN_M < abs(shift) < _LIVE_MAX_M:
        raise RuntimeError(
            f"vertical transform looks dead: NAVD88 -> EGM96 shift at "
            f"({lat}, {lon}) came back {shift:+.3f} m from a plain unit "
            "conversion. pyproj will null-transform a height when a vertical "
            "CRS is missing, the operand is 2-D, or the geoid grid is absent "
            "— returning it untouched with no warning (0.118 m error "
            "observed). Expected a small real separation; install the PROJ "
            "geoid grids (e.g. us_noaa_g2018u0.tif and us_nga_egm96_15.tif) "
            "or pass a pinned shift (pin=).")
    return shift
