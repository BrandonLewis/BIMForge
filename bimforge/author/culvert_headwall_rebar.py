"""Caltrans D90 headwall reinforcement: wall verticals + footing bars (sizes/
spacing per the B3 Type-1 reference), the pipe-distribution bars (#6 typical,
schedule-driven) around a CONCRETE (RC) pipe opening only (metal pipe uses
manufacturer hook bolts, not rebar), and wingwall verticals. Weight-only bars
for the LB pay quantity + BBS,
matching the R23 wingwall/barrier precedent (same RebarBuilder/bar_stations/Bar
machinery).

Each bar's LENGTH is a scalar -- its geometry run plus RebarBuilder hook
allowances -- built as a straight `Bar` so `Bar.length` equals that scalar
exactly; weight = length x plf (BAR_PROPS). 3D bent-bar solids are out of scope
here (mirrors wingwall_rebar); the scalar length is exact for the LB pay
quantity and the BBS.
"""
from __future__ import annotations

from bimforge.author.primitives import RebarBuilder, bar_stations


def _straight_bar(rb: RebarBuilder, mark: str, host: str, length: float,
                  shape: str = "straight"):
    """A mark whose centreline is a straight run of `length` ft (hooks/laps are
    already folded into `length`)."""
    return rb.bar(mark, host, [(0.0, 0.0, 0.0), (0.0, 0.0, length)], shape)


def headwall_bars(wall_length: float, design_h: float, footing_w: float,
                  pipe: dict, wingwalls: list, schedule: dict,
                  cover_in: float = 2.0) -> list:
    """All reinforcing bars for a D90 headwall + its wingwalls.

    R25 puts the headwall and both wingwalls on ONE continuous toe/heel
    footing, so the reinforcing covers the wingwall footings and the corner
    joints as well.

    Marks: `wall_vert` (panel verticals @spacing, length = H + hook),
    `footing` (transverse bars @spacing, full footing width `footing_w`, run
    under the headwall AND stationed along each wingwall leg so the whole
    continuous footing is covered -- size/spacing from `schedule["footing"]`),
    `pipe_dist` (distribution bars -- #6 typical, schedule-driven -- around an
    RC pipe opening, exactly `count` of them, ZERO for a metal/CMP pipe which
    uses manufacturer hook bolts), `wing_vert` (one set of verticals per
    wingwall, length = H + hook), `corner` (top & bottom bars at each
    headwall<->wingwall footing joint -- exactly 4 per corner (2 top + 2
    bottom), one corner per wingwall, `schedule["footing"]` size, each
    developed across the footing width so length = `footing_w`), and
    `wall_dowel` (wall/wingwall verticals dowelled/hooked into the footing --
    `schedule["wall_vert"]` size/spacing, one dowel per `wall_vert` station and
    one per `wing_vert` station, length = a nominal 2 ft lap plus the builder's
    hook allowance = `2.0 + rb.hook`).

    An unrecognized pipe `material` raises ValueError rather than silently
    falling through to the no-rebar branch and under-counting pay steel.
    """
    out: list = []

    # wall verticals along the panel length
    wv = schedule["wall_vert"]
    r = RebarBuilder(size=int(wv["size"]), cover_in=cover_in,
                     spacing_in=float(wv["spacing_in"]))
    for _ in bar_stations(0.0, wall_length, float(wv["spacing_in"]) / 12.0):
        _straight_bar(r, "wall_vert", "headwall panel", design_h + r.hook, "L")
    out += r.bars

    # footing transverse bars -- under the headwall AND along each wingwall leg
    # (R25: one continuous toe/heel footing). Same size/spacing throughout.
    fb = schedule["footing"]
    fb_sp = float(fb["spacing_in"]) / 12.0
    rf = RebarBuilder(size=int(fb["size"]), cover_in=cover_in,
                      spacing_in=float(fb["spacing_in"]))
    for _ in bar_stations(0.0, wall_length, fb_sp):
        _straight_bar(rf, "footing", "headwall footing", footing_w)
    for i, ww in enumerate(wingwalls, start=1):
        for _ in bar_stations(0.0, float(ww["length_ft"]), fb_sp):
            _straight_bar(rf, "footing", f"wingwall {i} footing", footing_w)
    out += rf.bars

    # corner bars -- top & bottom at each headwall<->wingwall footing joint.
    # Exactly 4 per corner (2 top + 2 bottom), one corner per wingwall. Same
    # size as the footing run; each developed across the footing width.
    for i, ww in enumerate(wingwalls, start=1):
        rc = RebarBuilder(size=int(fb["size"]), cover_in=cover_in,
                          spacing_in=float(fb["spacing_in"]))
        for _ in range(4):
            _straight_bar(rc, "corner", f"corner {i}", footing_w)
        out += rc.bars

    # pipe-distribution bars -- RC (concrete) pipe only; metal pipe uses
    # manufacturer hook bolts, not rebar. Fail loud on an unrecognized
    # material rather than silently under-counting pay steel.
    material = str(pipe.get("material", "rc")).strip().lower()
    RC = {"rc", "rcp", "concrete"}
    METAL = {"metal", "cmp", "steel"}
    if material in RC:
        pd = schedule["pipe_dist"]
        rp = RebarBuilder(size=int(pd["size"]), cover_in=cover_in,
                          spacing_in=12.0)
        for _ in range(int(pd["count"])):
            _straight_bar(rp, "pipe_dist", "pipe opening",
                          float(pipe["dia_ft"]) + 2 * rp.hook, "straight")
        out += rp.bars
    elif material not in METAL:
        raise ValueError(
            f"pipe material {material!r} not recognized "
            f"(expected one of {sorted(RC | METAL)})")
    # metal -> no distribution bars (manufacturer hook bolts)

    # wingwall verticals -- one set per wingwall
    wg = schedule["wing_vert"]
    for i, ww in enumerate(wingwalls, start=1):
        rw = RebarBuilder(size=int(wg["size"]), cover_in=cover_in,
                          spacing_in=float(wg["spacing_in"]))
        for _ in bar_stations(0.0, float(ww["length_ft"]),
                              float(wg["spacing_in"]) / 12.0):
            _straight_bar(rw, "wing_vert", f"wingwall {i}",
                          design_h + rw.hook, "L")
        out += rw.bars

    # wall dowels -- wall/wingwall verticals hooked into the footing. Sized like
    # the wall verticals; one dowel per wall_vert station and one per wing_vert
    # station. Length = nominal 2 ft lap + the builder's hook allowance.
    rd = RebarBuilder(size=int(wv["size"]), cover_in=cover_in,
                      spacing_in=float(wv["spacing_in"]))
    dowel_len = 2.0 + rd.hook
    for _ in bar_stations(0.0, wall_length, float(wv["spacing_in"]) / 12.0):
        _straight_bar(rd, "wall_dowel", "headwall footing", dowel_len, "L")
    for i, ww in enumerate(wingwalls, start=1):
        for _ in bar_stations(0.0, float(ww["length_ft"]),
                              float(wv["spacing_in"]) / 12.0):
            _straight_bar(rd, "wall_dowel", f"wingwall {i} footing",
                          dowel_len, "L")
    out += rd.bars

    return out
