"""Explicit per-run section rings for the barrier families (#26): a "Mod"
barrier (a light pedestal, a different stem set-back, chamfers) gives its
section as `runs[].profile` and keeps the family's end blocks, rebar and
validation.

    runs:
      - name: NB
        straight_length_ft: 120.0
        profile: [[0.3333, 0], [1.75, 0], [1.2708, 2.9], ...]   # x toward traffic, z up
        nose_profile: [[...], ...]     # optional; or {approach: [...], departure: [...]}

A ring is listed in the family's frame, either way round (the 842's own
rings run counter-clockwise, the 732SW's clockwise), and replaces the
computed section outright, so it cannot be combined with that family's Mod
dimension keys. The end-block loft pairs the running ring with the nose ring
by index, so the two must have the same vertex count and morph without
turning inside out.
"""
from __future__ import annotations

from bimforge.author.primitives import _signed_area2

#: the top band, as a fraction of the height above the base datum (z = 0),
#: in which `plumb_nose` looks for where the traffic and back faces start
_TOP_BAND = 0.75


def _seg_cross(p1, p2, p3, p4) -> bool:
    """True iff open segments p1p2 and p3p4 properly cross."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _crosses_itself(ring: list) -> bool:
    n = len(ring)
    edges = [(ring[i], ring[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue                    # adjacent through the closing edge
            if _seg_cross(*edges[i], *edges[j]):
                return True
    return False


def check_ring(ring, what: str) -> list[tuple[float, float]]:
    """A section ring as [(x, z)] floats: at least 3 vertices, not crossing
    itself, enclosing some area."""
    try:
        pts = [(float(x), float(z)) for x, z in ring]
    except (TypeError, ValueError):
        raise ValueError(f"{what}: a ring is a list of [x, z] pairs") from None
    if len(pts) < 3:
        raise ValueError(f"{what}: a ring needs at least 3 vertices, got {len(pts)}")
    if _crosses_itself(pts):
        raise ValueError(f"{what}: the ring crosses itself")
    if abs(_signed_area2(pts)) <= 1e-12:
        raise ValueError(f"{what}: the ring encloses no area")
    return pts


def check_pair(inboard: list, nose: list, what: str) -> None:
    """The loft morphs `inboard` into `nose` vertex by vertex: the counts must
    match, no edge may turn back on its partner (one may shrink to nothing,
    as a daylighting step does), and every ring along the way must stay a
    simple polygon wound the same way. A nose listed from a different start
    vertex, or the other way round, fails one of these."""
    if len(inboard) != len(nose):
        raise ValueError(f"{what}: the running ring ({len(inboard)} vertices) and "
                         f"the nose ring ({len(nose)}) cannot pair by index")
    n = len(inboard)
    sign = 1.0 if _signed_area2(inboard) > 0 else -1.0
    turned = any(
        (inboard[(i + 1) % n][0] - inboard[i][0]) * (nose[(i + 1) % n][0] - nose[i][0])
        + (inboard[(i + 1) % n][1] - inboard[i][1]) * (nose[(i + 1) % n][1] - nose[i][1])
        < -1e-9 for i in range(n))
    mids = ([(a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))
             for a, b in zip(inboard, nose)] for u in (0.25, 0.5, 0.75))
    wound = sign * _signed_area2(nose) > 0
    if turned or not wound or any(_crosses_itself(m) or sign * _signed_area2(m) <= 0.0
                                  for m in mids):
        raise ValueError(f"{what}: the running and nose rings do not pair "
                         f"by index (the loft turns inside out between them); "
                         f"start both at the same corner")


def plumb_nose(ring: list) -> list[tuple[float, float]]:
    """The end-block nose of a sloping-face ring, by substitution so vertex
    count and order survive (B11-82 Section G-G): the traffic face goes plumb
    on the top face line, so its base pulls in, and the back face goes plumb
    on its top, so a back-face step daylights out.

    Each face starts at the outermost vertex of the top band (the upper
    quarter of the height above z = 0: a chamfer vertex counts) and runs
    toward the base, through the first vertex at or below z = 0; every
    vertex on it beyond the plumb line moves onto it. Below the base datum
    (a footing) nothing moves. For a standard 842 ring this is exactly
    `type_842_profile(face="vertical")`. Either winding works."""
    pts = [(float(x), float(z)) for x, z in ring]
    if _signed_area2(pts) < 0:
        return list(reversed(plumb_nose(list(reversed(pts)))))
    n = len(pts)
    h = max(z for _, z in pts)
    if h <= 0.0:
        raise ValueError("plumb_nose: the ring has no height above z = 0")
    band = [i for i, (_, z) in enumerate(pts) if z >= _TOP_BAND * h]
    front = max(band, key=lambda i: (pts[i][0], pts[i][1]))
    back = min(band, key=lambda i: (pts[i][0], -pts[i][1]))
    out = list(pts)
    for start, step in ((front, -1), (back, 1)):
        x_line = pts[start][0]
        i = start
        for _ in range(n):
            x, z = pts[i]
            out[i] = (min(x, x_line), z)
            if z <= 0.0:
                break
            i = (i + step) % n
    return out


def chamfer_top(ring: list, c: float) -> list[tuple[float, float]]:
    """Cut every corner on the top of the ring (z at its maximum) back `c` ft
    along both of its edges: B11-82's 1" chamfers, typical. Each corner
    becomes two vertices, so a running ring and its nose chamfered alike
    still pair by index."""
    pts = [(float(x), float(z)) for x, z in ring]
    h = max(z for _, z in pts)
    n = len(pts)
    out = []
    for i, p in enumerate(pts):
        if abs(p[1] - h) > 1e-9:
            out.append(p)
            continue
        for q in (pts[i - 1], pts[(i + 1) % n]):
            d = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) ** 0.5
            if c >= d / 2.0:            # two chamfers meeting on one edge
                raise ValueError(f"a {c * 12:g}\" chamfer does not fit the "
                                 f"{d * 12:.2f}\" edge at ({p[0]:g}, {p[1]:g})")
            out.append((p[0] + (q[0] - p[0]) * c / d, p[1] + (q[1] - p[1]) * c / d))
    return out


def custom_rings(run: dict, kind: str | None, *, what: str,
                 mod_keys=(), derive_nose: bool = True):
    """(inboard, nose) for a run carrying `profile`, or None for a standard
    run. `nose` is None when `kind` is None (no end block asked for);
    otherwise it is the run's `nose_profile` (one ring, or one per end kind),
    else `plumb_nose` of the profile when the family's nose is a plumbed
    running section (`derive_nose`), else an error."""
    if "profile" not in run:
        if "nose_profile" in run:
            raise ValueError(f"{what}: nose_profile needs a profile")
        return None
    clash = sorted(k for k in mod_keys if k in run)
    if clash:
        raise ValueError(f"{what}: profile replaces the computed section; drop "
                         f"{', '.join(clash)} (or draw them into the ring)")
    inboard = check_ring(run["profile"], f"{what} profile")
    if kind is None:
        return inboard, None
    given = run.get("nose_profile")
    if isinstance(given, dict):
        given = given.get(kind)
    if given is not None:
        nose = check_ring(given, f"{what} nose_profile ({kind})")
    elif derive_nose:
        nose = plumb_nose(inboard)
    else:
        raise ValueError(f"{what}: a profile run with a {kind} end block needs "
                         f"nose_profile (one ring, or {{approach: ..., "
                         f"departure: ...}}): this family's nose is not a "
                         f"plumbed running section")
    check_pair(inboard, nose, what)
    return inboard, nose
