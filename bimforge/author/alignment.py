"""Alignment kernel: tangent/curve traverse, vertical profile, vertical-datum
chain, and standard-plan wall sections keyed on design H.

Ported from the bridge-pilot fork of the Work-repo lineage — the most complete of the
seven generations (`_resolve_pob` anchor form kept; offsets are RADIAL,
perpendicular to the tangent at the station, which matters on a 1,400 ft
radius where a densified polyline would introduce chord error).

Everything here is pure geometry; nothing writes files. Scalar survey math
(`dms`, `bearing_to_azimuth`, `forward`, `station`) lives in
:mod:`bimforge.cad.formats` — this module adds only the string-parsing front
ends its YAML dialect needs and delegates the arithmetic.

Examples:
    from bimforge.author.alignment import load
    m = load("bridge.yaml")
    n, e = m.align.station_offset(7220.83, 33.73, "Rt")
    z = m.profile.elev(7218.04)
"""
from __future__ import annotations

import math
from pathlib import Path

import yaml

from bimforge.cad.formats import bearing_to_azimuth as _bearing_to_azimuth
from bimforge.cad.formats import dms as _dms
from bimforge.cad.formats import forward as fwd
from bimforge.cad.formats import station as sta

FT_PER_M = 3937.0 / 1200.0          # US survey feet per metre
M_PER_FT = 1200.0 / 3937.0


# --------------------------------------------------------------------- helpers
def parse_dms(text) -> float:
    """'40-51-47' or '56-17-32.22' -> decimal degrees."""
    parts = [float(x) for x in str(text).split("-")]
    while len(parts) < 3:
        parts.append(0.0)
    return _dms(*parts[:3])


def parse_bearing(bearing: str) -> float:
    """'S 82-50-40.44 E' -> azimuth degrees clockwise from north."""
    ns, ang, ew = bearing.split(" ", 2)
    parts = [float(x) for x in ang.split("-")]
    while len(parts) < 3:
        parts.append(0.0)
    return _bearing_to_azimuth(ns.strip(), *parts[:3], ew.strip())


def parse_batter(text) -> float:
    """'0.5:12' -> 0.5/12 horizontal run per unit rise. 'NONE' -> 0.0."""
    s = str(text).strip().upper()
    if s in ("NONE", "0", ""):
        return 0.0
    num, den = s.split(":")
    return float(num) / float(den)


# ------------------------------------------------------------------- alignment
class Alignment:
    """Tangent/curve traverse with exact station-offset resolution."""

    def __init__(self, pob: dict, run: list[dict], name: str = "P") -> None:
        self.name = name
        self.pob = pob
        self.segments: list[dict] = []
        n, e = pob["northing"], pob["easting"]
        station = pob["station"]
        az = pob.get("azimuth")          # None unless a leading curve seeds it

        for seg in run:
            if seg["kind"] == "tangent":
                az = parse_bearing(seg["bearing"])
                end_n, end_e = fwd(n, e, az, seg["length"])
                self.segments.append({
                    "kind": "tangent", "s0": station, "s1": station + seg["length"],
                    "n0": n, "e0": e, "az": az, "length": seg["length"],
                })
                n, e, station = end_n, end_e, station + seg["length"]
                continue

            if az is None:
                raise ValueError("curve before any tangent - no incoming azimuth")
            delta = parse_dms(seg["delta"])
            sign = 1.0 if seg.get("turn", "R") == "R" else -1.0
            cn, ce = fwd(n, e, az + sign * 90.0, seg["radius"])
            radial0 = math.degrees(math.atan2(e - ce, n - cn))   # centre -> BC
            self.segments.append({
                "kind": "curve", "s0": station, "s1": station + seg["length"],
                "cn": cn, "ce": ce, "radius": seg["radius"], "delta": delta,
                "sign": sign, "radial0": radial0, "az0": az, "length": seg["length"],
                "no": seg.get("no"),
            })
            station += seg["length"]
            az += sign * delta
            n, e = fwd(cn, ce, radial0 + sign * delta, seg["radius"])

        self.s_start = pob["station"]
        self.s_end = station
        self.end_point = (n, e)

    # -- core ---------------------------------------------------------------
    def point_az(self, station: float) -> tuple[float, float, float]:
        """(northing, easting, tangent azimuth) exactly at a station.

        Stations before the POB or past the end are carried on the first/last
        segment produced by extending it, so wall LOLs that start upstation of
        the structure still resolve.
        """
        seg = self._seg_at(station)

        if seg["kind"] == "tangent":
            d = station - seg["s0"]
            n, e = fwd(seg["n0"], seg["e0"], seg["az"], d)
            return n, e, seg["az"] % 360.0

        frac = (station - seg["s0"]) / seg["length"]
        a = seg["radial0"] + seg["sign"] * seg["delta"] * frac
        n, e = fwd(seg["cn"], seg["ce"], a, seg["radius"])
        az = (seg["az0"] + seg["sign"] * seg["delta"] * frac) % 360.0
        return n, e, az

    def _seg_at(self, station: float) -> dict:
        """The segment covering a station (point_az's selection rule:
        outside the traverse, the first/last segment extends)."""
        for s in self.segments:
            if s["s0"] - 1e-6 <= station <= s["s1"] + 1e-6:
                return s
        return self.segments[0] if station < self.s_start else self.segments[-1]

    def curvature(self, station: float) -> float:
        """Signed plan curvature 1/R: positive = curving LEFT, negative =
        right, 0.0 on tangents. Left-positive pairs with `left_normal` so
        a point at +x offset under kappa > 0 lies toward the centre of
        curvature (its swept path is SHORTER: factor 1 - kappa*x)."""
        seg = self._seg_at(station)
        if seg["kind"] == "tangent":
            return 0.0
        return -seg["sign"] / seg["radius"]

    def left_normal(self, station: float) -> tuple[float, float]:
        """Unit (dn, de) toward the Lt side (azimuth - 90 deg) — the +x
        axis of a swept section at this station."""
        _n, _e, az = self.point_az(station)
        a = math.radians(az - 90.0)
        return math.cos(a), math.sin(a)

    def seg_breaks(self, s0: float, s1: float) -> list[float]:
        """Segment-end stations strictly inside (s0, s1)."""
        lo, hi = min(s0, s1), max(s0, s1)
        return [s["s1"] for s in self.segments
                if lo + 1e-9 < s["s1"] < hi - 1e-9]

    def kink_check(self, s0: float, s1: float) -> list[str]:
        """Azimuth continuity at joins strictly inside (s0, s1). The
        traverse legitimately kinks (wall LOLs turn corners); a SWEPT run
        must be tangent-continuous, so the sweep refuses on these."""
        fail = []
        lo, hi = min(s0, s1), max(s0, s1)
        for a, b in zip(self.segments, self.segments[1:]):
            if not (lo + 1e-9 < a["s1"] < hi - 1e-9):
                continue
            az_out = (a["az"] if a["kind"] == "tangent"
                      else a["az0"] + a["sign"] * a["delta"])
            az_in = b["az"] if b["kind"] == "tangent" else b["az0"]
            d = (az_in - az_out + 180.0) % 360.0 - 180.0
            if abs(d) > 1e-6:
                fail.append(
                    f"{self.name}: {abs(d):.6f} deg kink at station "
                    f"{sta(a['s1'])} - a swept run must be tangent-continuous")
        return fail

    def station_offset(self, station: float, offset: float, side: str) -> tuple[float, float]:
        """Exact radial offset. side 'Rt'/'R' is right of increasing station."""
        n, e, az = self.point_az(station)
        s = str(side).strip().upper()
        if s in ("RT", "R", "RIGHT"):
            return fwd(n, e, az + 90.0, offset)
        if s in ("LT", "L", "LEFT"):
            return fwd(n, e, az - 90.0, offset)
        raise ValueError(f"bad side {side!r}")

    def densify(self, s0: float, s1: float, step: float = 2.0) -> list[tuple[float, float, float]]:
        """[(n, e, station)] between two stations, tight enough for CAD.

        `step` is the maximum station spacing in survey feet; the range is
        divided evenly, so actual spacing is <= step. s1 < s0 walks the
        alignment backward (stations decrease point to point).
        """
        steps = max(2, int(math.ceil(abs(s1 - s0) / step)))
        out = []
        for i in range(steps + 1):
            s = s0 + (s1 - s0) * i / steps
            n, e, _ = self.point_az(s)
            out.append((n, e, s))
        return out

    def offset_curve(self, s0: float, s1: float, offset: float, side: str,
                     step: float = 2.0) -> list[tuple[float, float, float]]:
        """[(n, e, station)] of the radial offset line between two stations.

        Each point is exactly `station_offset(s, offset, side)`; `step` is the
        maximum station spacing in survey feet (same conventions as densify).
        """
        steps = max(2, int(math.ceil(abs(s1 - s0) / step)))
        out = []
        for i in range(steps + 1):
            s = s0 + (s1 - s0) * i / steps
            n, e = self.station_offset(s, offset, side)
            out.append((n, e, s))
        return out

    # -- checks -------------------------------------------------------------
    def closure(self, check: dict) -> dict:
        n, e = self.end_point
        dn = n - check["northing"]
        de = e - check["easting"]
        run = self.s_end - self.s_start
        d = math.hypot(dn, de)
        return {"computed_n": n, "computed_e": e,
                "published_n": check["northing"], "published_e": check["easting"],
                "dn": dn, "de": de, "dist": d, "run": run,
                "precision": (run / d) if d > 1e-9 else float("inf"),
                "station_computed": self.s_end, "station_published": check["station"]}


# --------------------------------------------------------------------- profile
class Profile:
    """Symmetric parabolic vertical curves joined by grade tangents."""

    def __init__(self, curves: list[dict]) -> None:
        self.curves = curves

    def elev(self, station: float) -> float:
        for c in self.curves:
            if c["bvc_station"] <= station <= c["evc_station"]:
                x = station - c["bvc_station"]
                g1 = c["g_in_pct"] / 100.0
                g2 = c["g_out_pct"] / 100.0
                r = (g2 - g1) / c["length_ft"]
                return c["bvc_elev"] + g1 * x + 0.5 * r * x * x

        first, last = self.curves[0], self.curves[-1]
        if station < first["bvc_station"]:
            return first["bvc_elev"] + (first["g_in_pct"] / 100.0) * (station - first["bvc_station"])
        if station > last["evc_station"]:
            return last["evc_elev"] + (last["g_out_pct"] / 100.0) * (station - last["evc_station"])

        # on a tangent between two curves
        for a, b in zip(self.curves, self.curves[1:]):
            if a["evc_station"] <= station <= b["bvc_station"]:
                return a["evc_elev"] + (a["g_out_pct"] / 100.0) * (station - a["evc_station"])
        raise ValueError(f"station {sta(station)} not on profile")

    def grade(self, station: float) -> float:
        """Analytic grade (ft/ft): g1 + r*x inside a curve, the governing
        tangent grade elsewhere (matching elev()'s selection exactly)."""
        for c in self.curves:
            if c["bvc_station"] <= station <= c["evc_station"]:
                x = station - c["bvc_station"]
                g1 = c["g_in_pct"] / 100.0
                g2 = c["g_out_pct"] / 100.0
                return g1 + (g2 - g1) * x / c["length_ft"]
        first, last = self.curves[0], self.curves[-1]
        if station < first["bvc_station"]:
            return first["g_in_pct"] / 100.0
        if station > last["evc_station"]:
            return last["g_out_pct"] / 100.0
        for a, b in zip(self.curves, self.curves[1:]):
            if a["evc_station"] <= station <= b["bvc_station"]:
                return a["g_out_pct"] / 100.0
        raise ValueError(f"station {sta(station)} not on profile")

    def breaks(self, s0: float, s1: float) -> list[float]:
        """BVC/EVC stations strictly inside (s0, s1)."""
        lo, hi = min(s0, s1), max(s0, s1)
        out = {s for c in self.curves
               for s in (c["bvc_station"], c["evc_station"])
               if lo + 1e-9 < s < hi - 1e-9}
        return sorted(out)

    def deck_elev(self, station: float, offset: float, cross_slope_pct: float) -> float:
        """Top of deck at a transverse offset from the crown at the control line."""
        return self.elev(station) + (cross_slope_pct / 100.0) * abs(offset)


# ----------------------------------------------------------------------- datum
class Datum:
    """Project vertical datum (NGVD29) -> NAVD88 -> EGM96 (KML altitude).

    Guarded: pyproj happily returns a "ballpark vertical transformation" with a
    ZERO shift when the VERTCON/geoid grids are absent, which would silently put
    every 3D element ~3.5 ft low. verify() refuses that outcome.
    """

    VERTCON = "us_noaa_vertconw.tif"
    GEOID18 = "us_noaa_g2018u0.tif"
    EGM96 = "us_nga_egm96_15.tif"

    # NGS datasheet for PID JS0517 (designation "F 127", El Dorado County).
    BM = {"lat": 38.7275, "lon": -120.8237, "ngvd29_m": 511.350, "navd88_m": 512.21}

    def __init__(self, epsg_grid: int = 2226) -> None:
        self.epsg_grid = epsg_grid
        self._built = False

    def _ensure(self) -> None:
        """Build the pyproj transformers on first use (lazy).

        Construction is deferred so instantiating a Datum can never fail;
        any pyproj failure (typically missing PROJ grid files) surfaces on
        the first conversion call as a clear RuntimeError instead of a
        cryptic pyproj traceback from deep inside model code.
        """
        if self._built:
            return
        try:
            from pyproj import Transformer

            self._T = Transformer
            self._to_ll = Transformer.from_crs(self.epsg_grid, 4326, always_xy=True)
            self._v88 = self._pipe(f"+step +inv +proj=vgridshift +grids={self.VERTCON}")
            self._egm = self._pipe(
                f"+step +inv +proj=vgridshift +grids={self.VERTCON} "
                f"+step +proj=vgridshift +grids={self.GEOID18} "
                f"+step +inv +proj=vgridshift +grids={self.EGM96}")
        except Exception as exc:
            raise RuntimeError(
                f"Datum transforms unavailable: {exc}. PROJ grid files "
                f"({self.VERTCON}, {self.GEOID18}, {self.EGM96}) may be "
                "missing — run Datum.verify() for details.") from exc
        self._built = True

    @property
    def to_ll(self):
        self._ensure()
        return self._to_ll

    def _pipe(self, steps: str):
        return self._T.from_pipeline(
            "+proj=pipeline +step +proj=axisswap +order=2,1 "
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad " + steps +
            " +step +proj=unitconvert +xy_in=rad +xy_out=deg "
            "+step +proj=axisswap +order=2,1")

    def lonlat(self, northing: float, easting: float) -> tuple[float, float]:
        lon, lat = self.to_ll.transform(easting, northing)
        return lon, lat

    def ngvd29_to_navd88_m(self, h_ft: float, lat: float, lon: float) -> float:
        self._ensure()
        return self._v88.transform(lat, lon, h_ft * M_PER_FT)[2]

    def ngvd29_to_egm96_m(self, h_ft: float, lat: float, lon: float) -> float:
        """KML absolute altitude, in metres."""
        self._ensure()
        return self._egm.transform(lat, lon, h_ft * M_PER_FT)[2]

    def verify(self, tol_m: float = 0.10) -> dict:
        """Check the chain against the NGS benchmark. Raises if it null-transforms."""
        got = self.ngvd29_to_navd88_m(self.BM["ngvd29_m"] * FT_PER_M,
                                      self.BM["lat"], self.BM["lon"])
        shift = got - self.BM["ngvd29_m"]
        resid = got - self.BM["navd88_m"]
        if abs(shift) < 1e-4:
            raise RuntimeError(
                "NGVD29->NAVD88 produced a ZERO shift: the PROJ grid "
                f"{self.VERTCON} is missing, so pyproj fell back to a ballpark "
                "null transform. Install the grid into pyproj's proj data dir.")
        if abs(resid) > tol_m:
            raise RuntimeError(
                f"NGVD29->NAVD88 off by {resid:+.3f} m at NGS PID JS0517 "
                f"(tolerance {tol_m} m).")
        net = self.ngvd29_to_egm96_m(1681.69, self.BM["lat"], self.BM["lon"]) * FT_PER_M - 1681.69
        return {"shift_m": shift, "residual_m": resid, "net_ngvd29_to_egm96_ft": net}


# ---------------------------------------------------------------- wall section
class WallSection:
    """Caltrans B3 retaining-wall section as a function of design H.

    Local 2D coordinates, origin at the top of footing on the stem FRONT face:
        x = horizontal, positive toward the RETAINED side (into the backfill)
        y = vertical, positive up; y = 0 is top of footing

    Supported types (sheet -> geometry), read off the 2025 B3 DGN sheets:
      1   (B3-1A): front (exposed) face VERTICAL, back face battered; W/C/B/F/T
                   and the back batter all tabulated per design H (H 4'-36').
      1a  (B3-3A): a DISTINCT type -- constant-thickness VERTICAL stem (no
                   batter) on a spread footing; W/C/B tabulated (H 4'-12'),
                   stem T = 1'-0" and footing F = 1'-2" constant.
      5   (B3-4A): front face BATTERED, back face vertical; only total footing
                   width W tabulated (H 4'-12') with a per-H front batter, and
                   stem top T = 11-1/2", footing F = 1'-6", toe 1'-4" constant.
      6a  (B3-7A): short masonry/concrete VERTICAL stem, H <= 6'; only W
                   tabulated (H 3'-4"..6'-0"), stem T = 7-5/8" (8" nominal),
                   footing F = 1'-0", toe 8" constant.
      6b  (B3-7A): as 6a but the stem sits near the toe (long heel); its own W
                   table, same constant stem/footing.

    W == C + B on every type: C is the toe (footing toe edge to stem FRONT
    face), B the heel (front face to footing heel edge; the stem base lies
    inside the B span). Design H is the stem height, top of footing to top of
    wall.
    """

    TYPE5_TOE_FT = 1.3333          # B3-4A spread footing section: 1'-4" toe

    def __init__(self, wall_type, H: float, tables: dict) -> None:
        # int 1/5 or str "1a"/"6a"/"6b" -> normalised lower-case tag
        self.wall_type = str(wall_type).strip().lower()
        self.H = float(H)
        wt = self.wall_type

        if wt in ("1", "1a"):
            tt = tables["type_1_case_1" if wt == "1" else "type_1a_case_1"]
            t = self._lookup(tt["table"], H)
            self.W, self.C, self.B = t["W_ft"], t["C_ft"], t["B_ft"]
            if wt == "1":
                self.T, self.F = t["T_ft"], t["F_ft"]
                self.batter = parse_batter(t["batter"])
            else:                        # 1a: constant vertical stem, no batter
                self.T = tt["stem_thickness_ft"]
                self.F = tt["footing_thickness_ft"]
                self.batter = 0.0
            self.front = "vertical"
        elif wt == "5":
            tt = tables["type_5_case_1"]
            t = self._lookup(tt["table"], H)
            self.T = tt["stem_top_thickness_ft"]
            self.F = tt["footing_thickness_ft"]
            self.W = t["W_ft"]
            self.batter = parse_batter(t["batter"])
            self.C = self.TYPE5_TOE_FT + self.batter * self.H
            self.B = self.W - self.C
            self.front = "battered"
        elif wt in ("6a", "6b"):
            tt = tables[f"type_{wt}_case_1"]
            t = self._lookup(tt["table"], H)
            self.T = tt["stem_thickness_ft"]
            self.F = tt["footing_thickness_ft"]
            self.W = t["W_ft"]
            self.batter = 0.0
            self.C = tt["toe_ft"]        # W tabulated only; toe is constant
            self.B = self.W - self.C
            self.front = "vertical"
        else:
            raise ValueError(f"unsupported wall type {wall_type!r}")

        self.stem_base_thickness = self.T + self.batter * self.H

    @staticmethod
    def _lookup(table: dict, H: float) -> dict:
        """Nearest tabulated design H at or above the requested one.

        The B3 sheets note "Design H may be exceeded by 6 in before going to the
        next size", so round UP to the next tabulated size. Keys may be int or
        float feet (Type 6 uses 8-in increments); the original key is preserved.
        """
        pairs = sorted((float(k), k) for k in table)
        for fk, k in pairs:
            if H <= fk + 0.5:
                return table[k]
        raise ValueError(
            f"design H {H} ft exceeds the tabulated range {pairs[-1][0]} ft")

    # -- section outlines ---------------------------------------------------
    def stem_polygon(self) -> list[tuple[float, float]]:
        H, T, b = self.H, self.T, self.batter
        if self.front == "battered":
            # type 5: front face battered, back face vertical at x = T
            return [(-b * H, 0.0), (0.0, H), (T, H), (T, 0.0)]
        # vertical front face at x = 0; back face battered (b = 0 => rectangle)
        return [(0.0, 0.0), (0.0, H), (T, H), (T + b * H, 0.0)]

    def footing_polygon(self) -> list[tuple[float, float]]:
        x_toe = -self.C
        x_heel = x_toe + self.W
        return [(x_toe, -self.F), (x_heel, -self.F), (x_heel, 0.0), (x_toe, 0.0)]

    def area_sf(self) -> float:
        return poly_area(self.stem_polygon()) + poly_area(self.footing_polygon())

    def front_face_x(self, y: float) -> float:
        """Horizontal position of the exposed face at height y above top of footing."""
        if self.front == "battered":
            return -self.batter * (self.H - y)
        return 0.0


def poly_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace area of a closed 2D polygon (public: the primitives use it too).

    Vertices are shifted to the first point before the sum: on absolute
    State-Plane coordinates the x1*y2 - x2*y1 terms catastrophically cancel
    (the bim/ifc_mesh.mesh_volume lesson; 2.3% measured error on the origin
    job). Area is translation-invariant, so the shift is free insurance for
    any world-coordinate caller."""
    if not pts:
        return 0.0
    x0, y0 = pts[0]
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    return abs(a) / 2.0


# ------------------------------------------------------------------ container
class AlignmentModel:
    """The parsed alignment YAML: control line, profile, datum, wall tables.

    `profile` is None when the YAML has no `profile:` block (headwall-class
    structures have none).
    """

    def __init__(self, data: dict) -> None:
        self.data = data
        pl = data["p_line"]
        self.align = Alignment(_resolve_pob(pl), pl["run"], name=pl.get("name", "P"))
        self.profile = Profile(data["profile"]["curves"]) if "profile" in data else None
        self.wall_tables = data.get("caltrans_wall_types", {})
        self._datum = None

    @property
    def datum(self) -> Datum:
        if self._datum is None:
            self._datum = Datum(self.data["datum"]["horizontal"]["epsg"])
        return self._datum

    def wall_section(self, wall_type: int, H: float) -> WallSection:
        return WallSection(wall_type, H, self.wall_tables)

    def wall(self, name: str) -> dict:
        return self.data["retaining_walls"][name]


def _resolve_pob(pl: dict) -> dict:
    """Return the run's start point, either given directly or derived.

    Two YAML forms are supported:
      pob    - station/northing/easting of the run's first vertex
      anchor - a published coordinate at some station further along the FIRST
               tangent, plus run_start_station; the start is back-computed along
               that tangent's reverse bearing (the bridge-pilot form, anchored on a
               published bearing coordinate when the full alignment is not yet
               transcribed).
    """
    if "pob" in pl:
        return pl["pob"]
    a = pl["anchor"]
    s0 = pl["run_start_station"]
    first = pl["run"][0]
    if first["kind"] != "tangent":
        raise ValueError("anchor form requires the run to start with a tangent")
    az = parse_bearing(first["bearing"])
    n, e = fwd(a["northing"], a["easting"], az + 180.0, a["station"] - s0)
    return {"station": s0, "northing": n, "easting": e}


def load(path: Path | str) -> AlignmentModel:
    """Parse an alignment YAML. The path is REQUIRED — no module-level default."""
    with open(path, "r", encoding="utf-8") as fh:
        return AlignmentModel(yaml.safe_load(fh))
