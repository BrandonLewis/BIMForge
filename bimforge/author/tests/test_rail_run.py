import math

import pytest

from bimforge.author import rail_run as rr
from bimforge.author import rail_section as rs
from bimforge.author.rail_run import build_run


def test_two_posts_minimum_and_endpoints():
    st = rr.post_stations(9.0)                 # one bay fits within max
    assert st[0] == 0.0 and st[-1] == 9.0
    assert len(st) >= 2


def test_bays_never_exceed_max():
    st = rr.post_stations(100.0)               # nominal 6'-2"
    bays = [b - a for a, b in zip(st, st[1:])]
    assert max(bays) <= 9.5 + 1e-9
    assert min(bays) >= 5.0 - 1e-9
    # bays are equal
    assert max(bays) - min(bays) < 1e-9


def test_bay_near_nominal():
    st = rr.post_stations(24.0)                # ~4 bays of 6.0
    bays = [b - a for a, b in zip(st, st[1:])]
    assert all(abs(b - 6.0) < 1e-9 for b in bays)


def test_nonpositive_length_fails_loud():
    with pytest.raises(ValueError):
        rr.post_stations(0.0)


def test_infeasible_band_prefers_ceiling_over_floor():
    # 9.6 ft: 1 bay (9.6) would exceed the 9.5 max; 2 bays (4.8) dip below the
    # 5.0 min. max is HARD, min is SOFT -> choose 2 bays, never exceed the max.
    st = rr.post_stations(9.6)
    bays = [b - a for a, b in zip(st, st[1:])]
    assert max(bays) <= 9.5 + 1e-9      # ceiling never breached
    assert len(st) == 3                 # 2 bays (3 posts), not 1


def _by_kind(els, token):
    return [e for e in els if token in e.name]


def test_build_run_rails_and_posts():
    els = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                       anchorage=False, end_posts=(), joints=())
    top = _by_kind(els, "top rail")
    lower = _by_kind(els, "lower rail")
    posts = _by_kind(els, "post ")
    assert len(top) == 1 and len(lower) == 1
    # top rail is the payment element: IfcRailing + explicit length_ft
    assert top[0].ifc_class == "IfcRailing"
    assert math.isclose(top[0].quantities["length_ft"], 24.0)
    # top rail weight-volume = net section area x length
    assert math.isclose(top[0].quantities["volume_cf"],
                        rs.area_sf("HSS3x2x3/16") * 24.0, rel_tol=1e-9)
    # 24 ft at ~6 ft bays -> 5 posts
    assert len(posts) == 5
    # a post is a hollow vertical member of height = config height
    p = posts[0]
    assert math.isclose(p.quantities["volume_cf"],
                        rs.area_sf("HSS2x2x3/16") * rs.CONFIG_B11_51.height_ft,
                        rel_tol=1e-9)


def test_swept_members_do_not_leak_cross_section_area_sf():
    """A SectionPrism/bent-tube member is swept along its length, so its
    area_sf is a CROSS-SECTION, not a plan footprint. It must not reach the
    element's quantities (emit_ifc would read it as a footprint). A vertical
    post is a Prism whose area_sf genuinely IS its footprint and is kept. (#252)
    """
    els = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                       anchorage=False, end_posts=("start", "end"), joints=(12.0,))
    swept = _by_kind(els, "rail") + _by_kind(els, "end return") \
        + _by_kind(els, "rail cap") + _by_kind(els, "splice sleeve")
    assert swept, "expected rails/returns/caps/sleeves in the run"
    for e in swept:
        assert "area_sf" not in e.quantities, f"{e.name} leaked a section area_sf"
    # a vertical post keeps its genuine plan footprint area_sf
    posts = _by_kind(els, "post ")
    assert posts and all("area_sf" in p.quantities for p in posts)


def test_top_rail_qto_length_is_declared_not_section_derived():
    """The payment rail's emitted Qto Length must be its declared length_ft
    (24.0), not a value derived from the leaked cross-section area_sf — the
    9.52-vs-166.77 regression — and it emits no bogus GrossArea. (#252)"""
    from bimforge.author.emit_ifc import base_quantities
    els = rr.build_run(length_ft=24.0, base_z_ft=0.0, run_name="NB",
                       anchorage=False, end_posts=(), joints=())
    rail, = [e for e in els if e.ifc_class == "IfcRailing"]
    qtys = base_quantities(rail, ft_to_m=1.0)
    assert [v for _, name, v in qtys if name == "Length"] == [pytest.approx(24.0)]
    assert not any(name == "GrossArea" for _, name, _ in qtys)


def test_top_rail_only_length_no_double_count():
    els = rr.build_run(length_ft=24.0, base_z_ft=0.0, run_name="NB",
                       anchorage=False, end_posts=(), joints=())
    with_len = [e for e in els if "length_ft" in e.quantities]
    assert [e.name for e in with_len] == ["NB top rail"]


def test_anchorage_mortar_and_dowels_per_post():
    els = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                       anchorage=True, end_posts=(), joints=())
    posts = _by_kind(els, "post ")
    mortar = _by_kind(els, "pocket mortar")
    dowels = _by_kind(els, "dowel")
    assert len(mortar) == len(posts)
    # net mortar = (4x5 - 2x2) in^2 x 9 in, per post
    net_cf = ((4 * 5 - 2 * 2) / 144.0) * (9.0 / 12.0)
    assert math.isclose(mortar[0].quantities["volume_cf"], net_cf, rel_tol=1e-9)
    # two dowel elements per post (each is a 2-bar set)
    assert len(dowels) == 2 * len(posts)
    long_set = [d for d in dowels if "2.5" in d.name][0]
    assert long_set.quantities["count"] == 2
    assert math.isclose(long_set.quantities["weight_lb"], 2 * 2.5 * 0.668,
                        rel_tol=1e-9)
    assert long_set.ifc_class == "IfcReinforcingBar"


def test_no_anchorage_when_flag_off():
    els = rr.build_run(length_ft=24.0, base_z_ft=0.0, run_name="NB",
                       anchorage=False, end_posts=(), joints=())
    assert not _by_kind(els, "mortar") and not _by_kind(els, "dowel")


def test_anchorage_on_by_default():
    els = rr.build_run(length_ft=24.0, base_z_ft=0.0, run_name="NB",
                       end_posts=(), joints=())   # anchorage omitted -> default True
    assert _by_kind(els, "pocket mortar")   # default emits anchorage
    assert _by_kind(els, "dowel")


def test_end_returns_and_caps_at_named_ends():
    els = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                       end_posts=("start", "end"), joints=())
    ret = _by_kind(els, "end return")
    caps = _by_kind(els, "rail cap")
    assert len(ret) == 2 and len(caps) == 2
    # true R=4' bent-down arc: swept steel = net area x R x sweep angle (the
    # rail drops its own height, ~47 deg -- NOT a full pi/2 quarter circle).
    phi = rr._return_sweep_angle(rs.CONFIG_B11_51.rails[0], rr.END_RETURN_RADIUS_FT)
    assert math.isclose(ret[0].quantities["volume_cf"],
                        rs.area_sf("HSS3x2x3/16") * rr.END_RETURN_RADIUS_FT * phi,
                        rel_tol=1e-9)
    # ... which is strictly less steel than the old straight pi/2 dev stub.
    assert (ret[0].quantities["volume_cf"]
            < rs.area_sf("HSS3x2x3/16") * math.pi / 2.0 * rr.END_RETURN_RADIUS_FT)
    assert "length_ft" not in ret[0].quantities
    # the two returns curl to DISTINCT ends: start beyond -Y, end beyond +Y.
    byend = {e.name.split()[-1]: e for e in ret}
    start_v = byend["start"].geometry.body_solids()[0]["verts"]
    end_v = byend["end"].geometry.body_solids()[0]["verts"]
    assert min(y for _x, y, _z in start_v) < 0.0 < max(y for _x, y, _z in end_v)
    # and it curls DOWN to the barrier top (base_z = 2.0), well below the
    # top-rail centerline (2.0 + 16").
    assert min(z for _x, _y, z in start_v) == pytest.approx(2.0, abs=1e-9)
    # cap is an IfcPlate
    assert all(c.ifc_class == "IfcPlate" for c in caps)


def test_reserved_run_name_rejected():
    with pytest.raises(ValueError, match="reserved element token"):
        rr.build_run(length_ft=24.0, run_name="lower rail")


def test_post_embeds_pocket_when_anchored():
    anc = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                       anchorage=True, end_posts=(), joints=())
    plain = rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                         anchorage=False, end_posts=(), joints=())
    p_anc = _by_kind(anc, "post ")[0]
    p_plain = _by_kind(plain, "post ")[0]
    embed = rr.POCKET_D_IN / 12.0
    h = rs.CONFIG_B11_51.height_ft
    assert math.isclose(p_plain.quantities["volume_cf"],
                        rs.area_sf("HSS2x2x3/16") * h, rel_tol=1e-9)
    assert math.isclose(p_anc.quantities["volume_cf"],
                        rs.area_sf("HSS2x2x3/16") * (h + embed), rel_tol=1e-9)


def test_joint_out_of_range_rejected():
    with pytest.raises(ValueError, match="outside the run"):
        rr.build_run(length_ft=24.0, run_name="NB", joints=(100.0,))


def test_duplicate_joints_rejected():
    with pytest.raises(ValueError, match="duplicate joint"):
        rr.build_run(length_ft=60.0, run_name="NB", joints=(30.0, 30.0))


def test_splice_sleeve_per_joint():
    els = rr.build_run(length_ft=60.0, base_z_ft=0.0, run_name="NB",
                       end_posts=(), joints=(30.0,))
    sleeves = _by_kind(els, "splice sleeve")
    assert len(sleeves) == 1
    s = sleeves[0]
    assert s.ifc_class == "IfcMember"
    assert "length_ft" not in s.quantities
    # centred on the joint station
    assert math.isclose(s.geometry.y0, 30.0 - rr.SLEEVE_LEN_FT / 2.0)
    # volume = liner net section (rail cavity wall = sleeve wall tw) x length
    b, d, t = (v / 12.0 for v in rs.HSS["HSS3x2x3/16"])
    tw = rr.SLEEVE_WALL_IN / 12.0
    ib, idp = b - 2 * t, d - 2 * t
    exp = (ib * idp - (ib - 2 * tw) * (idp - 2 * tw)) * rr.SLEEVE_LEN_FT
    assert math.isclose(s.quantities["volume_cf"], exp, rel_tol=1e-9)


def _geom_x_extent(el):
    """(min_x, max_x) over an element's geometry profile; None if weight-only."""
    g = getattr(el, "geometry", None)
    ring = getattr(g, "profile", None)          # SectionPrism: (x, z) points
    if ring is None:
        ring = getattr(g, "base", None)          # Prism: (x, y) points
    if not ring:
        return None
    xs = [p[0] for p in ring]
    return (min(xs), max(xs))


def test_x0_ft_shifts_every_element_transversely():
    a = build_run(24.0, base_z_ft=3.0, x0_ft=0.0)
    b = build_run(24.0, base_z_ft=3.0, x0_ft=2.5)
    assert len(a) == len(b) and len(a) > 0
    shifted = 0
    for ea, eb in zip(a, b):
        xa, xb = _geom_x_extent(ea), _geom_x_extent(eb)
        if xa is None:                           # dowels are weight-only
            assert xb is None
            continue
        assert xb[0] == pytest.approx(xa[0] + 2.5)
        assert xb[1] == pytest.approx(xa[1] + 2.5)
        shifted += 1
    assert shifted > 0                           # proves at least one solid moved


def test_x0_ft_defaults_to_zero_noop():
    # default (no x0_ft) must reproduce the explicit x0_ft=0.0 geometry
    d = build_run(18.0, base_z_ft=1.0)
    z = build_run(18.0, base_z_ft=1.0, x0_ft=0.0)
    for ed, ez in zip(d, z):
        assert _geom_x_extent(ed) == _geom_x_extent(ez)
