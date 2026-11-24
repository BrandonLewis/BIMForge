"""Section coordinates to survey points for the road corridor (P.6).

(u, v): u left of travel, v up from the profile grade line, in the plane
square to the alignment's 3D tangent. That is the sweep engine's "normal"
frame (SweptSection._xf), and the plane IFC4.3 puts an
IfcSectionedSolidHorizontal's sections in. The corridor places its courses,
its earthwork and its ground samples through `survey_point`, so all three
agree on where a section point is.
"""
from __future__ import annotations

import math

from bimforge.author.sweep import MAX_ARC_STEP_RAD, VC_SAGITTA_FT


def survey_point(alignment, profile, s: float, u: float, v: float) -> tuple:
    """(northing, easting, elevation) of section point (u, v) at station s."""
    n0, e0, az = alignment.point_az(s)
    ln, le = alignment.left_normal(s)
    a = math.radians(az)
    tn, te = math.cos(a), math.sin(a)
    gam = math.atan(profile.grade(s))
    sg, cg = math.sin(gam), math.cos(gam)
    # pitched about the left normal: +v tilts back toward -s uphill
    return (n0 + u * ln - v * sg * tn, e0 + u * le - v * sg * te,
            profile.elev(s) + v * cg)


def tangent3(alignment, profile, s: float) -> tuple:
    """The road's unit 3D tangent at station s, (north, east, up): the
    normal of the section plane `survey_point` builds. Analytic (the plan
    azimuth and the grade), so exact; a chord of survey points is not."""
    _n, _e, az = alignment.point_az(s)
    a = math.radians(az)
    g = profile.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    return (math.cos(a) * cg, math.sin(a) * cg, g * cg)


def densify(alignment, profile, stations: list) -> list:
    """`stations` with more between them where a plan curve or a vertical
    curve needs them, by the sweep engine's own step rules (SweptSection.
    _bays). `stations` must hold the alignment's segment breaks and the
    profile's BVC/EVC stations already."""
    out = []
    for a, b in zip(stations, stations[1:]):
        ds = b - a
        n = 1
        k = abs(alignment.curvature((a + b) / 2.0))
        if k > 0.0:
            n = max(n, math.ceil(k * ds / MAX_ARC_STEP_RAD))
        # grade() is the left limit at a shared station: sample inside
        eps = 1e-9 * ds
        dg = abs(profile.grade(b - eps) - profile.grade(a + eps))
        if dg > 1e-12:
            n = max(n, math.ceil(ds / math.sqrt(8.0 * VC_SAGITTA_FT * ds / dg)))
        out.extend(a + ds * i / n for i in range(n))
    out.append(stations[-1])
    return out


#: stations closer than this are one station, feet
STATION_TOL_FT = 1e-6


def merge_stations(have: list, more, tol: float = STATION_TOL_FT) -> list:
    """`have` (ascending, distinct) with each of `more` not within `tol` of
    a station already kept, ascending: two rails ending at one station, or
    a rail end on a wall's or a band's station, cut one section."""
    out = list(have)
    for s in sorted(more):
        if all(abs(s - k) > tol for k in out):
            out.append(s)
    return sorted(out)


def geometry_stations(al, prof, s0: float, s1: float) -> list:
    """The alignment's and the profile's own points strictly inside (s0,
    s1): segment ends (PC, PT, and the PI where tangents meet), and each
    vertical curve's BVC, PVI and EVC. frame.densify steps between the
    stations it is given and does not add these, so a section must be cut
    at each one."""
    # alignment.Profile's vertical curves are symmetric: the PVI is mid-curve
    pvis = [c["bvc_station"] + 0.5 * c["length_ft"] for c in prof.curves]
    out = set(al.seg_breaks(s0, s1)) | set(prof.breaks(s0, s1))
    out.update(s for s in pvis if s0 + 1e-9 < s < s1 - 1e-9)
    return sorted(out)
